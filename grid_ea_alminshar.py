import asyncio
import logging
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import firestore
from metaapi_cloud_sdk import MetaApi
import math

logger = logging.getLogger('AlMinshar')
logging.basicConfig(level=logging.INFO)

class AlMinsharGridEA:
    def __init__(self, user_id, api_token, account_id, db):
        self.user_id = user_id
        self.api_token = api_token
        self.account_id = account_id
        self.db = db
        self.api = MetaApi(api_token)
        self.account = None
        self.connection = None
        
        # Default Settings
        self.symbol = 'EURUSD'
        self.lot_size = 0.01
        self.grid_spacing = 50
        self.take_profit = 50
        self.stop_loss = 50
        self.max_pending = 50
        self.first_order_distance = 1.5
        self.close_opposite = False
        self.magic_number = hash(user_id) % 2147483647
        self.is_running = False

    async def _update_settings_from_db(self):
        doc = self.db.collection('users').document(self.user_id).get()
        if not doc.exists:
            return
        data = doc.to_dict()
        settings = data.get('bot_settings', {})
        self.symbol = settings.get('symbol', self.symbol)
        self.lot_size = float(settings.get('lot_size', self.lot_size))
        self.grid_spacing = float(settings.get('grid_spacing', self.grid_spacing))
        self.take_profit = float(settings.get('take_profit', self.take_profit))
        self.stop_loss = float(settings.get('stop_loss', self.stop_loss))
        self.max_pending = int(settings.get('max_pending', self.max_pending))
        self.first_order_distance = float(settings.get('first_order_distance', self.first_order_distance))
        self.close_opposite = bool(settings.get('close_opposite', self.close_opposite))
        self.is_running = bool(settings.get('is_running', self.is_running))

    async def connect(self):
        try:
            self.account = await self.api.metatrader_account_api.get_account(self.account_id)
            await self.account.wait_connected()
            self.connection = self.account.get_rpc_connection()
            await self.connection.connect()
            await self.connection.wait_synchronized()
            logger.info(f"[{self.user_id}] Connected to MT5 account {self.account_id}")
            return True
        except Exception as e:
            logger.error(f"[{self.user_id}] Error connecting to account: {e}")
            return False
            
    async def get_symbol_info(self):
        spec = await self.connection.get_symbol_specification(self.symbol)
        tick_value = spec.get('tickValue', 1.0)
        tick_size = spec.get('tickSize', 0.00001)
        point = spec.get('point', 0.00001)
        stops_level = spec.get('stopsLevel', 10) * point
        return tick_value, tick_size, point, stops_level

    def log_trade(self, action, details):
        self.db.collection('trade_logs').add({
            'user_id': self.user_id,
            'account_id': self.account_id,
            'timestamp': datetime.now(timezone.utc),
            'action': action,
            'details': details
        })

    async def update_positions_db(self, positions):
        pos_data = [p for p in positions if p.get('magic') == self.magic_number]
        self.db.collection('positions').document(self.user_id).set({
            'positions': pos_data,
            'updated_at': datetime.now(timezone.utc)
        })

    async def sync_grid(self):
        if not self.is_running:
            return

        try:
            price = await self.connection.get_symbol_price(self.symbol)
            ask = price['ask']
            bid = price['bid']
            
            tick_value, tick_size, point, stops_level = await self.get_symbol_info()
            
            first_dist_points = (self.first_order_distance / (tick_value * (self.lot_size / 0.01))) if tick_value else self.grid_spacing
            first_dist_price = max(first_dist_points * point, stops_level)
            grid_spacing_price = max(self.grid_spacing * point, stops_level)
            
            orders = await self.connection.get_orders()
            my_orders = [o for o in orders if o.get('symbol') == self.symbol and o.get('magic') == self.magic_number]
            
            positions = await self.connection.get_positions()
            my_positions = [p for p in positions if p.get('symbol') == self.symbol and p.get('magic') == self.magic_number]
            await self.update_positions_db(positions)
            
            # If close_opposite is true and position just opened
            if self.close_opposite and my_positions:
                for pos in my_positions:
                    pos_type = pos['type']
                    pos_price = pos['openPrice']
                    for o in my_orders:
                        if (pos_type == 'POSITION_TYPE_BUY' and o['type'] == 'ORDER_TYPE_SELL_STOP') or \
                           (pos_type == 'POSITION_TYPE_SELL' and o['type'] == 'ORDER_TYPE_BUY_STOP'):
                            dist = abs(o['openPrice'] - pos_price)
                            if dist <= 2 * grid_spacing_price:
                                await self.connection.cancel_order(o['id'])
                                logger.info(f"[{self.user_id}] Cancelled opposite order {o['id']}")
                                self.log_trade('cancel_order', o)
                                
            # Re-fetch orders after potential cancellations
            orders = await self.connection.get_orders()
            my_orders = [o for o in orders if o.get('symbol') == self.symbol and o.get('magic') == self.magic_number]
            
            buy_stops = [o['openPrice'] for o in my_orders if o['type'] == 'ORDER_TYPE_BUY_STOP']
            sell_stops = [o['openPrice'] for o in my_orders if o['type'] == 'ORDER_TYPE_SELL_STOP']
            
            if len(my_orders) >= self.max_pending:
                return

            expected_buy_starts = ask + first_dist_price
            expected_sell_starts = bid - first_dist_price
            
            tp_price = self.take_profit * point
            sl_price = self.stop_loss * point

            # Create buy stops
            for i in range(self.max_pending // 2):
                target_price = expected_buy_starts + (i * grid_spacing_price)
                if not any(abs(target_price - bp) < (point * 5) for bp in buy_stops):
                    if target_price - ask > stops_level:
                        try:
                            sl = target_price - sl_price if self.stop_loss > 0 else 0
                            tp = target_price + tp_price if self.take_profit > 0 else 0
                            await self.connection.create_stop_buy_order(
                                self.symbol, self.lot_size, target_price, sl, tp, 
                                options={'comment': 'AlMinshar Buy', 'magic': self.magic_number}
                            )
                            logger.info(f"[{self.user_id}] Placed Buy Stop at {target_price}")
                            self.log_trade('buy_stop', {'price': target_price, 'sl': sl, 'tp': tp})
                        except Exception as e:
                            logger.error(f"Failed to place buy stop: {e}")
                            
            # Create sell stops
            for i in range(self.max_pending // 2):
                target_price = expected_sell_starts - (i * grid_spacing_price)
                if not any(abs(target_price - sp) < (point * 5) for sp in sell_stops):
                    if bid - target_price > stops_level:
                        try:
                            sl = target_price + sl_price if self.stop_loss > 0 else 0
                            tp = target_price - tp_price if self.take_profit > 0 else 0
                            await self.connection.create_stop_sell_order(
                                self.symbol, self.lot_size, target_price, sl, tp,
                                options={'comment': 'AlMinshar Sell', 'magic': self.magic_number}
                            )
                            logger.info(f"[{self.user_id}] Placed Sell Stop at {target_price}")
                            self.log_trade('sell_stop', {'price': target_price, 'sl': sl, 'tp': tp})
                        except Exception as e:
                            logger.error(f"Failed to place sell stop: {e}")

        except Exception as e:
            logger.error(f"[{self.user_id}] Error in sync_grid: {e}")

    async def run(self):
        connected = await self.connect()
        if not connected:
            return
            
        while True:
            await self._update_settings_from_db()
            if self.is_running:
                await self.sync_grid()
            await asyncio.sleep(10) # 10 seconds tick

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python grid_ea_alminshar.py <user_id>")
        return
        
    user_id = sys.argv[1]
    
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()
    
    # Get user config
    doc = db.collection('users').document(user_id).get()
    if not doc.exists:
        logger.error("User not found")
        return
        
    user_data = doc.to_dict()
    account_id = user_data.get('mt5_credentials', {}).get('account_id')
    api_token = user_data.get('meta_api_token')
    
    if not account_id or not api_token:
        # Fallback to token manager
        from token_manager import get_best_token
        api_token = get_best_token(user_id)
        if not account_id:
            logger.error("No account ID configured")
            return
            
    bot = AlMinsharGridEA(user_id, api_token, account_id, db)
    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(bot.run())

if __name__ == "__main__":
    main()

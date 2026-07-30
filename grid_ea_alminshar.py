import asyncio
import logging
import time
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import firestore
from metaapi_cloud_sdk import MetaApi

logger = logging.getLogger('AlMinshar')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')

class AlMinsharGridEA:
    def __init__(self, user_id, api_token, account_id, db):
        self.user_id = user_id
        self.api_token = api_token
        self.account_id = account_id
        self.db = db
        self.api = MetaApi(api_token)
        self.account = None
        self.connection = None
        
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
        try:
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
        except Exception as e:
            logger.error(f"[{self.user_id}] Failed to read db settings: {e}")

    async def connect(self):
        try:
            self.account = await self.api.metatrader_account_api.get_account(self.account_id)
            if self.account.state != 'DEPLOYED':
                await self.account.deploy()
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
        try:
            self.db.collection('trade_logs').add({
                'user_id': self.user_id,
                'account_id': self.account_id,
                'timestamp': datetime.now(timezone.utc),
                'action': action,
                'details': details
            })
        except Exception as e:
            pass

    async def sync_grid(self):
        if not self.is_running or not self.connection:
            return

        try:
            price = await self.connection.get_symbol_price(self.symbol)
            ask = price['ask']
            bid = price['bid']
            
            tick_value, tick_size, point, stops_level = await self.get_symbol_info()
            
            first_dist_points = (self.first_order_distance / (tick_value * (self.lot_size / 0.01))) if tick_value else self.grid_spacing
            first_dist_price = max(first_dist_points * point, stops_level)
            grid_spacing_price = max(self.grid_spacing * point, stops_level)
            sl_price = self.stop_loss * point
            tp_price = self.take_profit * point

            orders = await self.connection.get_orders()
            my_orders = [o for o in orders if o.get('magic') == self.magic_number]
            buy_stops = [o for o in my_orders if o.get('type') == 'ORDER_TYPE_BUY_STOP']
            sell_stops = [o for o in my_orders if o.get('type') == 'ORDER_TYPE_SELL_STOP']
            
            # Simple grid refill logic
            if len(buy_stops) < self.max_pending // 2:
                level = ask + first_dist_price
                sl = level - sl_price if self.stop_loss > 0 else 0
                tp = level + tp_price if self.take_profit > 0 else 0
                try:
                    await self.connection.create_stop_buy_order(
                        self.symbol, self.lot_size, level, sl, tp,
                        options={'comment': 'AlMinshar Buy', 'magic': self.magic_number}
                    )
                except:
                    pass

            if len(sell_stops) < self.max_pending // 2:
                level = bid - first_dist_price
                sl = level + sl_price if self.stop_loss > 0 else 0
                tp = level - tp_price if self.take_profit > 0 else 0
                try:
                    await self.connection.create_stop_sell_order(
                        self.symbol, self.lot_size, level, sl, tp,
                        options={'comment': 'AlMinshar Sell', 'magic': self.magic_number}
                    )
                except:
                    pass

        except Exception as e:
            logger.error(f"[{self.user_id}] Error in sync_grid: {e}")

    async def run(self, max_duration_sec):
        start_time = time.time()
        connected = await self.connect()
        if not connected:
            return
            
        while True:
            if time.time() - start_time > max_duration_sec:
                logger.info(f"[{self.user_id}] Reached time limit. Exiting loop.")
                break
                
            await self._update_settings_from_db()
            if self.is_running:
                await self.sync_grid()
            await asyncio.sleep(5) 

async def run_all_users():
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    db = firestore.client()
    
    users_ref = db.collection('users')
    docs = users_ref.stream()
    
    tasks = []
    # 5.5 hours = 19800 seconds
    MAX_DURATION = 19800 
    
    for doc in docs:
        user_data = doc.to_dict()
        user_id = doc.id
        
        is_active = user_data.get('is_active', False)
        if not is_active:
            continue
            
        account_id = user_data.get('mt5_credentials', {}).get('account_id')
        api_token = user_data.get('meta_api_token') or user_data.get('assigned_meta_api_token')
        
        if not account_id or not api_token:
            continue
            
        bot = AlMinsharGridEA(user_id, api_token, account_id, db)
        tasks.append(bot.run(MAX_DURATION))
        
    if tasks:
        logger.info(f"Starting Grid EA for {len(tasks)} active users.")
        await asyncio.gather(*tasks)
    else:
        logger.info("No active users found with valid credentials. Sleeping for 1 minute before checking again...")
        # If no users, just sleep for a while so the action doesn't finish immediately
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(run_all_users())

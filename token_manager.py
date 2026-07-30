import firebase_admin
from firebase_admin import firestore
import logging

logger = logging.getLogger(__name__)

def _get_db():
    if not firebase_admin._apps:
        # Initialize with default credentials
        firebase_admin.initialize_app()
    return firestore.client()

def get_token_stats():
    """Retrieve token usage statistics."""
    db = _get_db()
    doc_ref = db.collection('system_config').document('backup_tokens')
    doc = doc_ref.get()
    if not doc.exists:
        return {}
    return doc.to_dict().get('tokens', {})

def get_best_token(user_id: str):
    """Find the token with the fewest users that has capacity."""
    stats = get_token_stats()
    best_token = None
    min_users = float('inf')
    
    for token, data in stats.items():
        # Check if user is already assigned to this token
        if user_id in data.get('users', []):
            return token
            
        max_accounts = data.get('max_accounts', 10)
        current_users = len(data.get('users', []))
        
        if current_users < max_accounts and current_users < min_users:
            min_users = current_users
            best_token = token
            
    if best_token:
        assign_user_to_token(user_id, best_token)
    return best_token

def assign_user_to_token(user_id: str, token: str):
    """Assign a user to a specific token."""
    db = _get_db()
    doc_ref = db.collection('system_config').document('backup_tokens')
    
    @firestore.transactional
    def update_in_transaction(transaction, ref):
        snapshot = transaction.get(ref)
        if not snapshot.exists:
            transaction.set(ref, {'tokens': {
                token: {
                    'max_accounts': 10,
                    'users': [user_id]
                }
            }})
            return
            
        data = snapshot.to_dict()
        tokens = data.get('tokens', {})
        
        # Remove user from any other token
        for t, d in tokens.items():
            if user_id in d.get('users', []):
                d['users'].remove(user_id)
                
        if token not in tokens:
            tokens[token] = {
                'max_accounts': 10,
                'users': []
            }
            
        if user_id not in tokens[token]['users']:
            tokens[token]['users'].append(user_id)
            
        transaction.update(ref, {'tokens': tokens})

    transaction = db.transaction()
    update_in_transaction(transaction, doc_ref)
    logger.info(f"Assigned user {user_id} to token {token[:5]}...")

def release_user_token(user_id: str):
    """Release user from any token they are assigned to."""
    db = _get_db()
    doc_ref = db.collection('system_config').document('backup_tokens')
    
    @firestore.transactional
    def release_in_transaction(transaction, ref):
        snapshot = transaction.get(ref)
        if not snapshot.exists:
            return
            
        data = snapshot.to_dict()
        tokens = data.get('tokens', {})
        updated = False
        
        for t, d in tokens.items():
            if user_id in d.get('users', []):
                d['users'].remove(user_id)
                updated = True
                
        if updated:
            transaction.update(ref, {'tokens': tokens})

    transaction = db.transaction()
    release_in_transaction(transaction, doc_ref)
    logger.info(f"Released token for user {user_id}")

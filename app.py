"""
HUD Properties Cloud Dashboard
Deployed on Render.com with Dropbox sync
"""

from flask import Flask, render_template, jsonify, request, send_file
from flask_cors import CORS
import sqlite3
# import pandas as pd  # Removed pandas to fix deployment
from datetime import datetime, timedelta
import json
import os
import dropbox
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import io
import traceback

app = Flask(__name__)
CORS(app)

# Configuration from environment variables
DROPBOX_TOKEN = os.environ.get('DROPBOX_TOKEN', '')
SYNC_INTERVAL = int(os.environ.get('SYNC_INTERVAL', 30))  # minutes
LOCAL_DB_PATH = '/tmp/hud_properties.db'  # Render uses /tmp for temporary files

logging.basicConfig(level=logging.INFO)

class DropboxDatabaseSync:
    """Sync database from Dropbox"""
    
    def __init__(self):
        self.token = DROPBOX_TOKEN
        self.local_db = LOCAL_DB_PATH
        self.last_sync = None
        self.sync_status = "Not initialized"
        
        if not self.token:
            logging.error("No Dropbox token provided!")
            self.enabled = False
            return
            
        try:
            self.dbx = dropbox.Dropbox(self.token)
            # Test connection
            self.dbx.users_get_current_account()
            logging.info("Dropbox connected successfully!")
            self.enabled = True
            self.sync_status = "Connected"
        except Exception as e:
            logging.error(f"Dropbox connection failed: {e}")
            self.enabled = False
            self.sync_status = f"Connection failed: {str(e)}"
    
    def sync_database(self):
        """Download latest database from Dropbox"""
        if not self.enabled:
            return False
            
        try:
            logging.info("Starting database sync from Dropbox...")
            
            # Download from Dropbox
            dropbox_path = "/hud-scraper-latest/hud_properties.db"
            metadata, response = self.dbx.files_download(dropbox_path)
            
            # Save to local temp file
            with open(self.local_db, 'wb') as f:
                f.write(response.content)
            
            self.last_sync = datetime.now()
            self.sync_status = f"Synced at {self.last_sync.strftime('%Y-%m-%d %H:%M:%S')}"
            
            # Get file info
            file_size = os.path.getsize(self.local_db) / (1024 * 1024)  # MB
            logging.info(f"Database synced successfully! Size: {file_size:.2f} MB")
            
            return True
            
        except dropbox.exceptions.ApiError as e:
            error_msg = f"Dropbox API error: {str(e)}"
            logging.error(error_msg)
            self.sync_status = error_msg
            
            # If file doesn't exist, create empty database
            if 'path/not_found' in str(e):
                logging.info("Creating empty database...")
                conn = sqlite3.connect(self.local_db)
                conn.execute('''CREATE TABLE IF NOT EXISTS properties 
                               (case_number TEXT, scrape_date DATE, state TEXT, 
                                address TEXT, price REAL, status TEXT)''')
                conn.close()
                self.sync_status = "No database in Dropbox yet - using empty database"
            
            return False
            
        except Exception as e:
            error_msg = f"Sync error: {str(e)}"
            logging.error(error_msg)
            self.sync_status = error_msg
            return False
    
    def get_last_update(self):
        """Get the last update time from database"""
        if not os.path.exists(self.local_db):
            return None
            
        try:
            conn = sqlite3.connect(self.local_db)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(scrape_date) FROM properties")
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else None
        except:
            return None

# Initialize sync
db_sync = DropboxDatabaseSync()

# Do initial sync
if db_sync.enabled:
    db_sync.sync_database()

# Setup automatic syncing
scheduler = BackgroundScheduler()
if db_sync.enabled:
    scheduler.add_job(
        func=db_sync.sync_database,
        trigger="interval",
        minutes=SYNC_INTERVAL,
        id='db_sync',
        name='Sync database from Dropbox',
        replace_existing=True
    )
    scheduler.start()
    logging.info(f"Scheduled sync every {SYNC_INTERVAL} minutes")

@app.route('/')
def index():
    """Main dashboard page"""
    return '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HUD Properties Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.plotly.com/plotly-latest.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        
        .header {
            background: white;
            border-radius: 12px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        
        .sync-status {
            background: #f0f9ff;
            border-left: 4px solid #3b82f6;
            padding: 15px;
            margin: 20px 0;
            border-radius: 6px;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: white;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            transition: transform 0.3s;
        }
        
        .stat-card:hover { transform: translateY(-5px); }
        
        .stat-label {
            color: #718096;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }
        
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            color: #2d3748;
        }
        
        .properties-table {
            background: white;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            overflow-x: auto;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        th {
            background: #f7fafc;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #4a5568;
            border-bottom: 2px solid #e2e8f0;
        }
        
        td {
            padding: 12px;
            border-bottom: 1px solid #e2e8f0;
        }
        
        tr:hover { background: #f7fafc; }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #718096;
        }
        
        .badge {
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .badge-new { background: #fef5e7; color: #f39c12; }
        .badge-reduced { background: #fce4e4; color: #e74c3c; }
        .badge-active { background: #e8f5e9; color: #27ae60; }
        
        .refresh-btn {
            background: #667eea;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
        }
        
        .refresh-btn:hover { background: #5a67d8; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="color: #2d3748; margin-bottom: 10px;">🏠 HUD Properties Dashboard</h1>
            <p style="color: #718096;">Real-time tracking of HUD foreclosure properties</p>
            
            <div class="sync-status" id="sync-status">
                <strong>Sync Status:</strong> <span id="sync-text">Loading...</span>
                <button class="refresh-btn" onclick="forceSync()" style="float: right;">Force Sync</button>
            </div>
        </div>
        
        <div class="stats-grid" id="stats-grid">
            <div class="loading">Loading statistics...</div>
        </div>
        
        <div class="properties-table">
            <h2 style="margin-bottom: 20px; color: #2d3748;">Current Properties</h2>
            <table id="properties-table">
                <thead>
                    <tr>
                        <th>Case #</th>
                        <th>Address</th>
                        <th>State</th>
                        <th>Price</th>
                        <th>Beds/Baths</th>
                        <th>Days on Market</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody id="properties-tbody">
                    <tr><td colspan="7" class="loading">Loading properties...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
    
    <script>
        // Load sync status
        async function loadSyncStatus() {
            try {
                const response = await fetch('/api/sync_status');
                const data = await response.json();
                document.getElementById('sync-text').innerHTML = 
                    `${data.status} | Last Update: ${data.last_update || 'Never'} | 
                     Database: ${(data.db_size / 1024 / 1024).toFixed(2)} MB`;
            } catch (e) {
                document.getElementById('sync-text').innerHTML = 'Error loading status';
            }
        }
        
        // Load dashboard statistics
        async function loadStats() {
            try {
                const response = await fetch('/api/dashboard_stats');
                const data = await response.json();
                
                const statsHtml = `
                    <div class="stat-card">
                        <div class="stat-label">Total Active</div>
                        <div class="stat-value">${data.total_active || 0}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">New Today</div>
                        <div class="stat-value">${data.new_today || 0}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Price Reduced</div>
                        <div class="stat-value">${data.reduced_today || 0}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Average Price</div>
                        <div class="stat-value">$${Math.round(data.avg_price || 0).toLocaleString()}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">States Tracked</div>
                        <div class="stat-value">${data.states || 0}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Last Scrape</div>
                        <div class="stat-value">${data.last_scrape || 'N/A'}</div>
                    </div>
                `;
                
                document.getElementById('stats-grid').innerHTML = statsHtml;
            } catch (e) {
                document.getElementById('stats-grid').innerHTML = 
                    '<div class="loading">Error loading statistics</div>';
            }
        }
        
        // Load properties table
        async function loadProperties() {
            try {
                const response = await fetch('/api/properties');
                const data = await response.json();
                
                if (data.properties.length === 0) {
                    document.getElementById('properties-tbody').innerHTML = 
                        '<tr><td colspan="7" class="loading">No properties found</td></tr>';
                    return;
                }
                
                const tbody = document.getElementById('properties-tbody');
                tbody.innerHTML = data.properties.map(p => `
                    <tr>
                        <td><strong>${p.case_number}</strong></td>
                        <td>${p.address || 'N/A'}</td>
                        <td>${p.state}</td>
                        <td><strong>$${(p.price || 0).toLocaleString()}</strong></td>
                        <td>${p.bedrooms || 0}/${p.bathrooms || 0}</td>
                        <td>${p.days_on_market || 0}</td>
                        <td><span class="badge badge-${getStatusClass(p.status)}">${p.status}</span></td>
                    </tr>
                `).join('');
            } catch (e) {
                document.getElementById('properties-tbody').innerHTML = 
                    '<tr><td colspan="7" class="loading">Error loading properties</td></tr>';
            }
        }
        
        function getStatusClass(status) {
            if (status?.includes('New')) return 'new';
            if (status?.includes('Reduced')) return 'reduced';
            return 'active';
        }
        
        // Force sync
        async function forceSync() {
            const btn = event.target;
            btn.disabled = true;
            btn.textContent = 'Syncing...';
            
            try {
                const response = await fetch('/api/force_sync');
                const data = await response.json();
                
                if (data.success) {
                    alert('Sync completed successfully!');
                    loadSyncStatus();
                    loadStats();
                    loadProperties();
                } else {
                    alert('Sync failed. Check logs.');
                }
            } catch (e) {
                alert('Error during sync: ' + e.message);
            }
            
            btn.disabled = false;
            btn.textContent = 'Force Sync';
        }
        
        // Initialize dashboard
        loadSyncStatus();
        loadStats();
        loadProperties();
        
        // Auto-refresh every 5 minutes
        setInterval(() => {
            loadSyncStatus();
            loadStats();
            loadProperties();
        }, 300000);
    </script>
</body>
</html>
    '''

@app.route('/api/sync_status')
def sync_status():
    """Get current sync status"""
    return jsonify({
        'status': db_sync.sync_status,
        'last_update': db_sync.get_last_update(),
        'last_sync': db_sync.last_sync.isoformat() if db_sync.last_sync else None,
        'db_size': os.path.getsize(LOCAL_DB_PATH) if os.path.exists(LOCAL_DB_PATH) else 0,
        'enabled': db_sync.enabled
    })

@app.route('/api/dashboard_stats')
def dashboard_stats():
    """Get dashboard statistics"""
    if not os.path.exists(LOCAL_DB_PATH):
        return jsonify({'error': 'No database found'})
    
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()
        
        # Get current date
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Get statistics
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT CASE WHEN status != 'Removed' THEN case_number END) as total_active,
                COUNT(DISTINCT CASE WHEN status = 'New Inventory' THEN case_number END) as new_today,
                COUNT(DISTINCT CASE WHEN status = 'Price Reduced' THEN case_number END) as reduced_today,
                AVG(CASE WHEN status != 'Removed' THEN price END) as avg_price,
                COUNT(DISTINCT state) as states,
                MAX(scrape_date) as last_scrape
            FROM properties
            WHERE scrape_date = (SELECT MAX(scrape_date) FROM properties)
        """)
        
        row = cursor.fetchone()
        if row:
            stats = {
                'total_active': row[0] or 0,
                'new_today': row[1] or 0,
                'reduced_today': row[2] or 0,
                'avg_price': row[3] or 0,
                'states': row[4] or 0,
                'last_scrape': row[5] or 'Never'
            }
        else:
            stats = {
                'total_active': 0,
                'new_today': 0,
                'reduced_today': 0,
                'avg_price': 0,
                'states': 0,
                'last_scrape': 'Never'
            }
        
        conn.close()
        return jsonify(stats)
        
    except Exception as e:
        logging.error(f"Error getting stats: {e}")
        return jsonify({'error': str(e)})

@app.route('/api/properties')
def get_properties():
    """Get property list"""
    if not os.path.exists(LOCAL_DB_PATH):
        return jsonify({'properties': []})
    
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        
        query = """
            SELECT DISTINCT
                p.case_number,
                p.address,
                p.state,
                p.price,
                p.bedrooms,
                p.bathrooms,
                p.status,
                CAST(
                    CASE 
                        WHEN pa.total_days_on_market IS NOT NULL 
                        THEN pa.total_days_on_market 
                        ELSE 0 
                    END AS INTEGER
                ) as days_on_market
            FROM properties p
            LEFT JOIN property_analytics pa ON p.case_number = pa.case_number
            WHERE p.scrape_date = (SELECT MAX(scrape_date) FROM properties)
                AND p.status != 'Removed'
            ORDER BY p.state, p.price
            LIMIT 100
        """
        
        # Execute query without pandas
        cursor = conn.execute(query)
        columns = [description[0] for description in cursor.description]
        properties = []
        for row in cursor.fetchall():
            properties.append(dict(zip(columns, row)))
        
        conn.close()
        
        return jsonify({'properties': properties})
        
    except Exception as e:
        logging.error(f"Error getting properties: {e}")
        logging.error(traceback.format_exc())
        return jsonify({'properties': [], 'error': str(e)})

@app.route('/api/force_sync')
def force_sync():
    """Manually trigger a sync"""
    success = db_sync.sync_database()
    return jsonify({
        'success': success,
        'timestamp': datetime.now().isoformat(),
        'status': db_sync.sync_status
    })

@app.route('/health')
def health():
    """Health check endpoint for Render"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

if __name__ == '__main__':
    # For local testing
    app.run(debug=True, port=5000)
else:
    # For production
    logging.info("Starting production server...")
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
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: white;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            transition: transform 0.3s;
            cursor: pointer;
            position: relative;
        }
        
        .stat-card:hover { 
            transform: translateY(-5px); 
            box-shadow: 0 8px 20px rgba(0,0,0,0.12);
        }
        
        .stat-card.active {
            border: 2px solid #667eea;
            background: #f0f4ff;
        }
        
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
        
        .filters-bar {
            background: white;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            align-items: center;
        }
        
        .filter-button {
            padding: 8px 16px;
            border: 2px solid #e2e8f0;
            background: white;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
            font-weight: 500;
        }
        
        .filter-button:hover {
            border-color: #667eea;
            background: #f0f4ff;
        }
        
        .filter-button.active {
            background: #667eea;
            color: white;
            border-color: #667eea;
        }
        
        .search-box {
            flex: 1;
            min-width: 200px;
        }
        
        .search-box input {
            width: 100%;
            padding: 10px 15px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 14px;
            transition: border 0.3s;
        }
        
        .search-box input:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .properties-table {
            background: white;
            border-radius: 12px;
            padding: 25px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.08);
            overflow-x: auto;
        }
        
        .table-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }
        
        .result-count {
            color: #718096;
            font-size: 14px;
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
            cursor: pointer;
            user-select: none;
        }
        
        th:hover {
            background: #e2e8f0;
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
        .badge-removed { background: #f0f0f0; color: #666; }
        
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
        
        select {
            padding: 10px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            background: white;
            cursor: pointer;
        }
        
        .clear-filters {
            background: #ef4444;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 500;
        }
        
        .clear-filters:hover {
            background: #dc2626;
        }
        
        .hidden { display: none; }
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
            <div class="stat-card" onclick="filterByStatus('all')">
                <div class="stat-label">Total Active</div>
                <div class="stat-value" id="total-active">0</div>
            </div>
            <div class="stat-card" onclick="filterByStatus('New Inventory')">
                <div class="stat-label">New Inventory</div>
                <div class="stat-value" id="new-today">0</div>
            </div>
            <div class="stat-card" onclick="filterByStatus('Price Reduced')">
                <div class="stat-label">Price Reduced</div>
                <div class="stat-value" id="reduced-today">0</div>
            </div>
            <div class="stat-card" onclick="filterByStatus('Existing')">
                <div class="stat-label">Existing</div>
                <div class="stat-value" id="existing">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Average Price</div>
                <div class="stat-value" id="avg-price">$0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Last Scrape</div>
                <div class="stat-value" id="last-scrape" style="font-size: 18px;">N/A</div>
            </div>
        </div>
        
        <div class="filters-bar">
            <select id="state-filter" onchange="applyFilters()">
                <option value="">All States</option>
                <option value="GA">Georgia</option>
                <option value="FL">Florida</option>
                <option value="TX">Texas</option>
                <option value="AL">Alabama</option>
                <option value="TN">Tennessee</option>
                <option value="SC">South Carolina</option>
                <option value="NC">North Carolina</option>
                <option value="KY">Kentucky</option>
                <option value="VA">Virginia</option>
                <option value="MS">Mississippi</option>
                <option value="WV">West Virginia</option>
                <option value="AR">Arkansas</option>
            </select>
            
            <select id="price-filter" onchange="applyFilters()">
                <option value="">All Prices</option>
                <option value="0-50000">Under $50k</option>
                <option value="50000-100000">$50k - $100k</option>
                <option value="100000-150000">$100k - $150k</option>
                <option value="150000-200000">$150k - $200k</option>
                <option value="200000-300000">$200k - $300k</option>
                <option value="300000-999999999">Over $300k</option>
            </select>
            
            <select id="beds-filter" onchange="applyFilters()">
                <option value="">All Beds</option>
                <option value="1">1 Bed</option>
                <option value="2">2 Beds</option>
                <option value="3">3 Beds</option>
                <option value="4">4+ Beds</option>
            </select>
            
            <div class="search-box">
                <input type="text" id="search-input" placeholder="Search by address or case number..." onkeyup="applyFilters()">
            </div>
            
            <button class="clear-filters" onclick="clearAllFilters()">Clear Filters</button>
        </div>
        
        <div class="properties-table">
            <div class="table-header">
                <h2 style="color: #2d3748;">Properties</h2>
                <div class="result-count">Showing <span id="result-count">0</span> properties</div>
            </div>
            
            <table id="properties-table">
                <thead>
                    <tr>
                        <th onclick="sortTable('case_number')">Case # ↕</th>
                        <th onclick="sortTable('address')">Address ↕</th>
                        <th onclick="sortTable('state')">State ↕</th>
                        <th onclick="sortTable('price')">Price ↕</th>
                        <th onclick="sortTable('bedrooms')">Beds/Baths ↕</th>
                        <th onclick="sortTable('days_on_market')">Days on Market ↕</th>
                        <th onclick="sortTable('status')">Status ↕</th>
                    </tr>
                </thead>
                <tbody id="properties-tbody">
                    <tr><td colspan="7" class="loading">Loading properties...</td></tr>
                </tbody>
            </table>
        </div>
    </div>
    
    <script>
        let allProperties = [];
        let filteredProperties = [];
        let currentStatusFilter = 'all';
        let sortColumn = 'state';
        let sortDirection = 'asc';
        
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
                
                document.getElementById('total-active').textContent = data.total_active || 0;
                document.getElementById('new-today').textContent = data.new_today || 0;
                document.getElementById('reduced-today').textContent = data.reduced_today || 0;
                document.getElementById('avg-price').textContent = '$' + Math.round(data.avg_price || 0).toLocaleString();
                document.getElementById('last-scrape').textContent = data.last_scrape || 'N/A';
                
                // Calculate existing
                const existing = (data.total_active || 0) - (data.new_today || 0) - (data.reduced_today || 0);
                document.getElementById('existing').textContent = Math.max(0, existing);
                
            } catch (e) {
                console.error('Error loading stats:', e);
            }
        }
        
        // Load properties
        async function loadProperties() {
            try {
                const response = await fetch('/api/properties');
                const data = await response.json();
                
                allProperties = data.properties || [];
                applyFilters();
                
            } catch (e) {
                document.getElementById('properties-tbody').innerHTML = 
                    '<tr><td colspan="7" class="loading">Error loading properties</td></tr>';
            }
        }
        
        // Filter by status (when clicking stat cards)
        function filterByStatus(status) {
            currentStatusFilter = status;
            
            // Update active card styling
            document.querySelectorAll('.stat-card').forEach(card => {
                card.classList.remove('active');
            });
            
            if (status !== 'all') {
                event.currentTarget.classList.add('active');
            } else {
                document.querySelectorAll('.stat-card')[0].classList.add('active');
            }
            
            applyFilters();
        }
        
        // Apply all filters
        function applyFilters() {
            const stateFilter = document.getElementById('state-filter').value;
            const priceFilter = document.getElementById('price-filter').value;
            const bedsFilter = document.getElementById('beds-filter').value;
            const searchTerm = document.getElementById('search-input').value.toLowerCase();
            
            filteredProperties = allProperties.filter(prop => {
                // Status filter
                if (currentStatusFilter !== 'all') {
                    if (currentStatusFilter === 'Existing') {
                        if (prop.status === 'New Inventory' || prop.status === 'Price Reduced') {
                            return false;
                        }
                    } else if (prop.status !== currentStatusFilter) {
                        return false;
                    }
                }
                
                // State filter
                if (stateFilter && prop.state !== stateFilter) {
                    return false;
                }
                
                // Price filter
                if (priceFilter) {
                    const [min, max] = priceFilter.split('-').map(Number);
                    const price = prop.price || 0;
                    if (price < min || price > max) {
                        return false;
                    }
                }
                
                // Beds filter
                if (bedsFilter) {
                    const beds = prop.bedrooms || 0;
                    if (bedsFilter === '4' && beds < 4) {
                        return false;
                    } else if (bedsFilter !== '4' && beds != bedsFilter) {
                        return false;
                    }
                }
                
                // Search filter
                if (searchTerm) {
                    const searchableText = (
                        (prop.case_number || '') + ' ' +
                        (prop.address || '')
                    ).toLowerCase();
                    
                    if (!searchableText.includes(searchTerm)) {
                        return false;
                    }
                }
                
                return true;
            });
            
            renderProperties();
        }
        
        // Clear all filters
        function clearAllFilters() {
            document.getElementById('state-filter').value = '';
            document.getElementById('price-filter').value = '';
            document.getElementById('beds-filter').value = '';
            document.getElementById('search-input').value = '';
            currentStatusFilter = 'all';
            
            document.querySelectorAll('.stat-card').forEach(card => {
                card.classList.remove('active');
            });
            
            applyFilters();
        }
        
        // Sort table
        function sortTable(column) {
            if (sortColumn === column) {
                sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                sortColumn = column;
                sortDirection = 'asc';
            }
            
            filteredProperties.sort((a, b) => {
                let valA = a[column];
                let valB = b[column];
                
                if (column === 'price' || column === 'bedrooms' || column === 'days_on_market') {
                    valA = Number(valA) || 0;
                    valB = Number(valB) || 0;
                }
                
                if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
                if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
                return 0;
            });
            
            renderProperties();
        }
        
        // Render properties table
        function renderProperties() {
            const tbody = document.getElementById('properties-tbody');
            document.getElementById('result-count').textContent = filteredProperties.length;
            
            if (filteredProperties.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="loading">No properties found</td></tr>';
                return;
            }
            
            tbody.innerHTML = filteredProperties.map(p => `
                <tr>
                    <td><strong>${p.case_number}</strong></td>
                    <td>${p.address || 'N/A'}</td>
                    <td>${p.state}</td>
                    <td><strong>$${(p.price || 0).toLocaleString()}</strong></td>
                    <td>${p.bedrooms || 0}/${p.bathrooms || 0}</td>
                    <td>${p.days_on_market || 0}</td>
                    <td><span class="badge badge-${getStatusClass(p.status)}">${p.status || 'Unknown'}</span></td>
                </tr>
            `).join('');
        }
        
        function getStatusClass(status) {
            if (status?.includes('New')) return 'new';
            if (status?.includes('Reduced')) return 'reduced';
            if (status?.includes('Removed')) return 'removed';
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
            LIMIT 1000
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
from flask import Flask, render_template, request, url_for, redirect, jsonify, session, flash
from flask_socketio import SocketIO
import os
from dotenv import load_dotenv 
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import json
from datetime import datetime
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

load_dotenv()  # Load environment variables

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default-secret-key')  # Use environment variable

# Add this for production
port = int(os.environ.get('PORT', 5000))

# Modify the socketio initialization for production
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Your original menu items
def get_menu_items(category):
    MENU_ITEMS = {
        "breakfast": [
            {"id": "masala-dosa", "name": "Masala Dosa", "price": 50, "image": "dosa.svg"},
            {"id": "plain-dosa", "name": "Plain Dosa", "price": 45, "image": "p_dosa.svg"},
            {"id": "onion-dosa", "name": "Onion Dosa", "price": 45, "image": "o_dosa.svg"},
            {"id": "idli-vada", "name": "Idli Vada", "price": 40, "image": "idli.svg"},
            {"id": "veg-palav", "name": "Veg Palav", "price": 50, "image": "palav.svg"},
            {"id": "lemon-rice", "name": "Lemon Rice", "price": 50, "image": "lemon.svg"},
            {"id": "puri", "name": "Puri", "price": 50, "image": "puri.svg"},
        ],
        "lunch": [
            {"id": "south-meals", "name": "South Meals", "price": 60, "image": "southmeal.svg"},
            {"id": "north-meal", "name": "North Meals", "price": 70, "image": "northlunch.svg"},
            {"id": "thalli", "name": "Thalli", "price": 120, "image": "thali.svg"},
            {"id": "allu-paratha", "name": "Allu Paratha", "price": 75, "image": "alluparata.svg"},
            {"id": "parota", "name": "Parota", "price": 50, "image": "parota.svg"},
            {"id": "neer-dose", "name": "Neer Dose", "price": 50, "image": "neerdose.svg"},
        ],
        "beverages": [
            {"id": "black-coffee", "name": "Black Coffee", "price": 25, "image": "blackcoffe.svg"},
            {"id": "cold-coffee", "name": "Cold Coffee", "price": 40, "image": "coldcofee.svg"},
            {"id": "masala-tea", "name": "Masala Tea", "price": 20, "image": "masala-t.svg"},
            {"id": "mint-tea", "name": "Mint Tea", "price": 25, "image": "mint-t.svg"},
            {"id": "filter-coffee", "name": "Filter Coffee", "price": 30, "image": "coffe.svg"},
        ]
    }
    return MENU_ITEMS.get(category, [])

# In-memory cart storage (use DB in production)
CART = {}

ADMINS_FILE = os.path.join('instance', 'admins.json')

def load_admins():
    if not os.path.exists(ADMINS_FILE):
        return []
    with open(ADMINS_FILE, 'r') as f:
        return json.load(f)

def save_admins(admins):
    with open(ADMINS_FILE, 'w') as f:
        json.dump(admins, f)

def find_admin(username):
    admins = load_admins()
    for admin in admins:
        if admin['username'] == username:
            return admin
    return None

# Helper to calculate cart total
def cart_total(cart):
    return sum(item['price'] * item['quantity'] for item in cart.values())

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/categories")
def categories():
    table_number = request.args.get('table_number')
    if table_number:
        session['table_number'] = table_number
    elif not session.get('table_number'):
        # If no table number in args or session, redirect to start
        return redirect(url_for('index'))
    return render_template("categories.html")

@app.route('/menu/<category>')
def menu(category):
    table_number = request.args.get('table_number', '')
    if not table_number:
        return redirect(url_for('index'))
    session['table_number'] = table_number
    menu_items = get_menu_items(category)
    if not menu_items:
        return redirect(url_for('categories'))
    return render_template('menu.html', category=category, menu_items=menu_items, table_number=table_number)

@app.route("/cart/<table_number>")
def cart(table_number):
    if not table_number or table_number != session.get('table_number'):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({"error": "Invalid session"}), 400
        return redirect(url_for('index'))

    table_cart = CART.get(table_number, {})
    cart_items = {k: v for k, v in table_cart.items() if k != '_meta'}
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(cart_items=cart_items)
        
    total = cart_total(cart_items)
    return render_template(
        "cart.html", 
        cart_items=cart_items, 
        table_number=table_number, 
        cart_total=total,
        # Pass the full cart with metadata for status display
        full_cart_data=table_cart 
    )

@app.route("/add_to_cart", methods=["POST"])
def add_to_cart():
    data = request.json
    table_number = session.get("table_number")
    if not table_number:
        return jsonify({"error": "Table number missing!"}), 400
    try:
        item_id = data["id"]
        name = data["name"]
        price = float(data["price"])
        if price < 0:
            return jsonify({"error": "Invalid price"}), 400
        if table_number not in CART:
            CART[table_number] = {"_meta": {"status": "Preparing", "last_updated": datetime.now().isoformat()}}
        if item_id in CART[table_number]:
            CART[table_number][item_id]["quantity"] += 1
        else:
            CART[table_number][item_id] = {"name": name, "price": price, "quantity": 1}
        # Update meta
        CART[table_number]["_meta"]["last_updated"] = datetime.now().isoformat()
        cart_count = sum(item["quantity"] for k, item in CART[table_number].items() if k != "_meta")
        socketio.emit("cart_update", {"cart_count": cart_count}, room=table_number)
        # Don't emit admin_cart_update here - only when order is confirmed
        return jsonify({"cart_count": cart_count, "total_items": cart_count})
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400

@app.route("/update_cart", methods=["POST"])
def update_cart():
    data = request.json
    table_number = session.get("table_number")
    if not table_number:
        return jsonify({"error": "Invalid table number"}), 400

    try:
        item_id = data["id"]
        quantity = int(data["quantity"])
        
        if table_number not in CART:
            CART[table_number] = {"_meta": {"status": "Preparing", "last_updated": datetime.now().isoformat()}}

        if quantity > 0:
            # Add item if it doesn't exist, otherwise update quantity
            if item_id not in CART[table_number]:
                 CART[table_number][item_id] = {
                    "name": data["name"], 
                    "price": float(data["price"]), 
                    "quantity": quantity
                }
            else:
                CART[table_number][item_id]["quantity"] = quantity
        elif item_id in CART[table_number]:
            # Remove item if quantity is 0 or less
            del CART[table_number][item_id]

        # Update meta and emit updates
        CART[table_number]["_meta"]["last_updated"] = datetime.now().isoformat()
        total_items = sum(item.get("quantity", 0) for k, item in CART[table_number].items() if k != "_meta")
        
        socketio.emit("cart_update", {"cart_count": total_items}, room=table_number)
        # Don't emit admin_cart_update here - only when order is confirmed
        
        return jsonify({"success": True, "total_items": total_items})
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400

@app.route("/update_cart_status", methods=["POST"])
@admin_required
def update_cart_status():
    table_number = request.form.get("table_number")
    status = request.form.get("status")
    if table_number in CART and "_meta" in CART[table_number]:
        CART[table_number]["_meta"]["status"] = status
        CART[table_number]["_meta"]["last_updated"] = datetime.now().isoformat()
        socketio.emit("admin_cart_update", {"carts": CART})
        return ("", 204)
    return ("Not found", 404)

@app.route("/get_cart_count")
def get_cart_count():
    table_number = session.get("table_number")
    count = sum(item["quantity"] for item in CART.get(table_number, {}).values()) if table_number else 0
    return jsonify({"count": count})

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        print(f"--- [DEBUG] Attempting login for username: '{username}'")
        print(f"--- [DEBUG] Password entered: '{password}'")

        admin = find_admin(username)
        if admin:
            print(f"--- [DEBUG] Admin found in file: {admin}")
            stored_hash = admin['password']
            is_password_correct = check_password_hash(stored_hash, password)
            print(f"--- [DEBUG] Password check result: {is_password_correct}")
            if is_password_correct:
                session['admin_logged_in'] = True
                session['admin_username'] = username
                print("--- [DEBUG] Login successful, redirecting...")
                return redirect(url_for('admin_panel'))
            else:
                print("--- [DEBUG] Login failed: Password hash does not match.")
        else:
            print(f"--- [DEBUG] Login failed: Admin '{username}' not found in file.")

        flash('Invalid credentials', 'danger')
    return render_template('admin_login.html')

@app.route('/admin_logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route("/admin")
@admin_required
def admin_panel():
    admins = load_admins()

    # --- Analytics Calculation ---
    item_to_category = {item['id']: category for category in ['breakfast', 'lunch', 'beverages'] for item in get_menu_items(category)}
    
    total_revenue = 0
    total_orders = 0
    item_counts = {}
    category_revenue = {"breakfast": 0, "lunch": 0, "beverages": 0}

    ordered_carts = {
        table: cart for table, cart in CART.items() 
        if cart.get("_meta", {}).get("status") in ["Ordered", "Cooking", "Served"]
    }
    
    total_orders = len(ordered_carts)

    for table, cart_data in ordered_carts.items():
        cart_items_only = {k: v for k, v in cart_data.items() if k != "_meta"}
        cart_total_val = cart_total(cart_items_only)
        total_revenue += cart_total_val
        
        for item_id, item_details in cart_items_only.items():
            item_counts[item_details['name']] = item_counts.get(item_details['name'], 0) + item_details['quantity']
            item_category = item_to_category.get(item_id)
            if item_category:
                category_revenue[item_category] += item_details['price'] * item_details['quantity']

    popular_items = sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    analytics = {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "popular_items": popular_items,
        "category_revenue": category_revenue
    }

    # Prepare cart data for template - only show confirmed orders
    cart_data = {}
    for table, items in CART.items():
        meta = items.get("_meta", {})
        status = meta.get("status", "Preparing")
        
        # Only include orders that have been confirmed (not just preparing)
        if status in ["Ordered", "Cooking", "Served"]:
            cart_items = {k: v for k, v in items.items() if k != "_meta"}
            # Only include if there are actual items
            if cart_items:
                cart_data[table] = {
                    "items": cart_items,
                    "status": status,
                    "last_updated": meta.get("last_updated", ""),
                    "total": cart_total(cart_items)
                }
    return render_template("admin.html", carts=cart_data, admins=admins, analytics=analytics)

@app.route("/delete_cart/<table_number>", methods=["POST"])
@admin_required
def delete_cart(table_number):
    if table_number in CART:
        # Save to database if it was an ordered cart (for analytics)
        cart_data = CART[table_number]
        meta = cart_data.get("_meta", {})
        if meta.get("status") in ["Ordered", "Cooking", "Served"]:
            cart_items = {k: v for k, v in cart_data.items() if k != "_meta"}
            if cart_items:
                total_amount = cart_total(cart_items)
                save_completed_order_to_db(table_number, cart_items, total_amount)
        
        del CART[table_number]
        socketio.emit("cart_deleted", {"table_number": table_number})
    return redirect(url_for('admin_panel'))

@app.route('/admin_add', methods=['POST'])
@admin_required
def admin_add():
    username = request.form.get('username')
    password = request.form.get('password')
    if not username or not password:
        flash('Username and password required', 'danger')
        return redirect(url_for('admin_panel'))
    if find_admin(username):
        flash('Admin already exists', 'danger')
        return redirect(url_for('admin_panel'))
    admins = load_admins()
    admins.append({
        'username': username,
        'password': generate_password_hash(password)
    })
    save_admins(admins)
    flash('Admin added', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin_remove', methods=['POST'])
@admin_required
def admin_remove():
    username = request.form.get('username')
    if not username:
        flash('Username required', 'danger')
        return redirect(url_for('admin_panel'))
    if username == session.get('admin_username'):
        flash('You cannot remove yourself', 'danger')
        return redirect(url_for('admin_panel'))
    admins = load_admins()
    admins = [a for a in admins if a['username'] != username]
    save_admins(admins)
    flash('Admin removed', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/submit_order', methods=['POST'])
def submit_order():
    table_number = session.get('table_number')
    if not table_number or table_number not in CART:
        return jsonify({'error': 'Invalid table number or empty cart'}), 400
    
    # Calculate order total for notification
    cart_items = {k: v for k, v in CART[table_number].items() if k != "_meta"}
    total_amount = cart_total(cart_items)
    item_count = sum(item["quantity"] for item in cart_items.values())
    
    # Mark the cart as ordered
    CART[table_number]['_meta']['status'] = 'Ordered'
    CART[table_number]['_meta']['last_updated'] = datetime.now().isoformat()
    
    # Save order to database for permanent analytics
    save_completed_order_to_db(table_number, cart_items, total_amount)
    
    # Emit order confirmation notification to admin with sound alert
    socketio.emit('order_confirmed_notification', {
        "table_number": table_number,
        "total_amount": total_amount,
        "item_count": item_count,
        "message": f"🎉 NEW ORDER CONFIRMED! Table {table_number} - {item_count} items - ₹{total_amount:.2f}"
    })
    
    socketio.emit('admin_cart_update', {'carts': CART})
    return jsonify({'success': True, 'message': 'Order placed successfully!'})

# Helper to save completed order to database for analytics
def save_completed_order_to_db(table_number, cart_items, total_amount):
    """Save completed order to database for permanent analytics tracking"""
    try:
        conn = sqlite3.connect('instance/restaurant.db')
        cursor = conn.cursor()
        
        # Get item category mapping
        item_to_category = {
            item['id']: category 
            for category in ['breakfast', 'lunch', 'beverages'] 
            for item in get_menu_items(category)
        }
        
        # Insert completed order
        order_date = datetime.now()
        cursor.execute('''
            INSERT INTO completed_orders (table_number, total_amount, order_date, completed_date)
            VALUES (?, ?, ?, ?)
        ''', (table_number, total_amount, order_date, order_date))
        
        order_id = cursor.lastrowid
        
        # Insert order items
        for item_id, item_details in cart_items.items():
            category = item_to_category.get(item_id, 'other')
            cursor.execute('''
                INSERT INTO order_items (order_id, item_name, item_price, quantity, category, order_date)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (order_id, item_details['name'], item_details['price'], 
                  item_details['quantity'], category, order_date))
        
        conn.commit()
        conn.close()
        print(f"Order saved to database: Table {table_number}, Total: ₹{total_amount}")
        
    except Exception as e:
        print(f"Error saving order to database: {e}")

@app.route('/api/analytics/overview')
@admin_required
def api_analytics_overview():
    """Get overview analytics data from database"""
    try:
        conn = sqlite3.connect('instance/restaurant.db')
        cursor = conn.cursor()
        
        # Get total revenue and orders from completed_orders
        cursor.execute('SELECT SUM(total_amount), COUNT(*) FROM completed_orders')
        result = cursor.fetchone()
        total_revenue = result[0] or 0
        total_orders = result[1] or 0
        
        # Calculate average order value
        avg_order = total_revenue / total_orders if total_orders > 0 else 0
        
        # Get category revenue
        cursor.execute('''
            SELECT category, SUM(item_price * quantity) as revenue
            FROM order_items
            GROUP BY category
        ''')
        category_data = cursor.fetchall()
        category_revenue = {cat: rev for cat, rev in category_data}
        
        # Find top category
        top_category = max(category_revenue, key=category_revenue.get) if category_revenue else "None"
        
        # Get last 7 days revenue data for chart
        cursor.execute('''
            SELECT DATE(order_date) as order_day, SUM(total_amount) as daily_revenue
            FROM completed_orders
            WHERE order_date >= date('now', '-7 days')
            GROUP BY DATE(order_date)
            ORDER BY order_day
        ''')
        daily_data = cursor.fetchall()
        
        # Prepare revenue chart data
        revenue_labels = []
        revenue_values = []
        for i in range(7):
            date = datetime.now() - timedelta(days=6-i)
            date_str = date.strftime('%Y-%m-%d')
            revenue_labels.append(date.strftime('%m/%d'))
            
            # Find revenue for this date
            day_revenue = 0
            for day, revenue in daily_data:
                if day == date_str:
                    day_revenue = revenue
                    break
            revenue_values.append(day_revenue)
        
        # Get category distribution for pie chart
        category_labels = list(category_revenue.keys())
        category_values = list(category_revenue.values())
        
        conn.close()
        
        return jsonify({
            'totalRevenue': total_revenue,
            'totalOrders': total_orders,
            'avgOrder': avg_order,
            'topCategory': top_category.title(),
            'revenueData': {
                'labels': revenue_labels,
                'values': revenue_values
            },
            'categoryData': {
                'labels': [cat.title() for cat in category_labels],
                'values': category_values
            }
        })
        
    except Exception as e:
        print(f"Error in overview analytics: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/daily')
@admin_required
def api_analytics_daily():
    """Get daily sales data for last 30 days"""
    try:
        conn = sqlite3.connect('instance/restaurant.db')
        cursor = conn.cursor()
        
        # Get daily data for last 30 days
        cursor.execute('''
            SELECT DATE(order_date) as order_day, 
                   SUM(total_amount) as daily_revenue,
                   COUNT(*) as daily_orders
            FROM completed_orders
            WHERE order_date >= date('now', '-30 days')
            GROUP BY DATE(order_date)
            ORDER BY order_day
        ''')
        daily_data = cursor.fetchall()
        
        # Prepare data for last 30 days
        labels = []
        revenue = []
        orders = []
        
        for i in range(30):
            date = datetime.now() - timedelta(days=29-i)
            date_str = date.strftime('%Y-%m-%d')
            labels.append(date.strftime('%m/%d'))
            
            # Find data for this date
            day_revenue = 0
            day_orders = 0
            for day, rev, ord_count in daily_data:
                if day == date_str:
                    day_revenue = rev or 0
                    day_orders = ord_count or 0
                    break
            
            revenue.append(day_revenue)
            orders.append(day_orders)
        
        conn.close()
        
        return jsonify({
            'labels': labels,
            'revenue': revenue,
            'orders': orders,
            'total_revenue': sum(revenue),
            'total_orders': sum(orders)
        })
        
    except Exception as e:
        print(f"Error in daily analytics: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/weekly')
@admin_required
def api_analytics_weekly():
    """Get weekly sales data for last 12 weeks"""
    try:
        conn = sqlite3.connect('instance/restaurant.db')
        cursor = conn.cursor()
        
        # Get weekly data for last 12 weeks
        cursor.execute('''
            SELECT strftime('%Y-%W', order_date) as week_year,
                   SUM(total_amount) as weekly_revenue,
                   COUNT(*) as weekly_orders
            FROM completed_orders
            WHERE order_date >= date('now', '-84 days')
            GROUP BY strftime('%Y-%W', order_date)
            ORDER BY week_year
        ''')
        weekly_data = cursor.fetchall()
        
        labels = []
        revenue = []
        orders = []
        
        # Generate last 12 weeks
        for i in range(12):
            # Calculate week start date
            week_start = datetime.now() - timedelta(weeks=11-i)
            week_year = week_start.strftime('%Y-%W')
            week_label = f"Week {week_start.strftime('%m/%d')}"
            labels.append(week_label)
            
            # Find data for this week
            week_revenue = 0
            week_orders = 0
            for wy, rev, ord_count in weekly_data:
                if wy == week_year:
                    week_revenue = rev or 0
                    week_orders = ord_count or 0
                    break
            
            revenue.append(week_revenue)
            orders.append(week_orders)
        
        conn.close()
        
        return jsonify({
            'labels': labels,
            'revenue': revenue,
            'orders': orders,
            'total_revenue': sum(revenue),
            'total_orders': sum(orders)
        })
        
    except Exception as e:
        print(f"Error in weekly analytics: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/monthly')
@admin_required
def api_analytics_monthly():
    """Get monthly sales data for last 12 months"""
    try:
        conn = sqlite3.connect('instance/restaurant.db')
        cursor = conn.cursor()
        
        # Get monthly data for last 12 months
        cursor.execute('''
            SELECT strftime('%Y-%m', order_date) as month_year,
                   SUM(total_amount) as monthly_revenue,
                   COUNT(*) as monthly_orders
            FROM completed_orders
            WHERE order_date >= date('now', '-12 months')
            GROUP BY strftime('%Y-%m', order_date)
            ORDER BY month_year
        ''')
        monthly_data = cursor.fetchall()
        
        labels = []
        revenue = []
        orders = []
        
        # Generate last 12 months
        for i in range(12):
            month_date = datetime.now().replace(day=1) - timedelta(days=32*i)
            month_date = month_date.replace(day=1)  # First day of month
            month_year = month_date.strftime('%Y-%m')
            month_label = month_date.strftime('%b %Y')
            labels.insert(0, month_label)  # Insert at beginning to maintain chronological order
            
            # Find data for this month
            month_revenue = 0
            month_orders = 0
            for my, rev, ord_count in monthly_data:
                if my == month_year:
                    month_revenue = rev or 0
                    month_orders = ord_count or 0
                    break
            
            revenue.insert(0, month_revenue)
            orders.insert(0, month_orders)
        
        conn.close()
        
        return jsonify({
            'labels': labels,
            'revenue': revenue,
            'orders': orders,
            'total_revenue': sum(revenue),
            'total_orders': sum(orders)
        })
        
    except Exception as e:
        print(f"Error in monthly analytics: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/popular')
@admin_required
def api_analytics_popular():
    """Get popular items and category distribution from database"""
    try:
        conn = sqlite3.connect('instance/restaurant.db')
        cursor = conn.cursor()
        
        # Get popular items from database
        cursor.execute('''
            SELECT item_name, SUM(quantity) as total_quantity
            FROM order_items
            GROUP BY item_name
            ORDER BY total_quantity DESC
            LIMIT 10
        ''')
        db_items = cursor.fetchall()
        
        # Get category distribution from database
        cursor.execute('''
            SELECT category, SUM(quantity) as total_quantity
            FROM order_items
            GROUP BY category
            ORDER BY total_quantity DESC
        ''')
        db_categories = cursor.fetchall()
        
        # Also include current in-memory orders for real-time data
        item_counts = defaultdict(int)
        category_counts = defaultdict(int)
        
        item_to_category = {
            item['id']: category 
            for category in ['breakfast', 'lunch', 'beverages'] 
            for item in get_menu_items(category)
        }
        
        # Process current in-memory orders
        ordered_carts = {
            table: cart for table, cart in CART.items() 
            if cart.get("_meta", {}).get("status") in ["Ordered", "Cooking", "Served"]
        }
        
        for table, cart_data in ordered_carts.items():
            cart_items_only = {k: v for k, v in cart_data.items() if k != "_meta"}
            for item_id, item_details in cart_items_only.items():
                item_counts[item_details['name']] += item_details['quantity']
                item_category = item_to_category.get(item_id, 'other')
                category_counts[item_category] += item_details['quantity']
        
        # Combine database and in-memory data for items
        combined_items = defaultdict(int)
        for item_name, quantity in db_items:
            combined_items[item_name] += quantity
        for item_name, quantity in item_counts.items():
            combined_items[item_name] += quantity
        
        # Combine database and in-memory data for categories
        combined_categories = defaultdict(int)
        for category, quantity in db_categories:
            combined_categories[category] += quantity
        for category, quantity in category_counts.items():
            combined_categories[category] += quantity
        
        # Sort and get top items
        popular_items = sorted(combined_items.items(), key=lambda x: x[1], reverse=True)[:10]
        
        conn.close()
        
        return jsonify({
            'items': {
                'labels': [item[0] for item in popular_items],
                'data': [item[1] for item in popular_items]
            },
            'categories': {
                'labels': [cat.title() for cat in combined_categories.keys()],
                'data': list(combined_categories.values())
            }
        })
        
    except Exception as e:
        print(f"Error in popular analytics: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/analytics')
@admin_required
def analytics():
    """Serve the analytics dashboard page"""
    return render_template('analytics.html')


def init_db():
    """Initialize the database tables if they don't exist."""
    try:
        conn = sqlite3.connect('instance/restaurant.db')
        cursor = conn.cursor()
        # Create completed_orders table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS completed_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                table_number TEXT,
                total_amount REAL,
                order_date TIMESTAMP,
                completed_date TIMESTAMP
            )
        ''')
        # Create order_items table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                item_name TEXT,
                item_price REAL,
                quantity INTEGER,
                category TEXT,
                order_date TIMESTAMP,
                FOREIGN KEY(order_id) REFERENCES completed_orders(id)
            )
        ''')
        conn.commit()
        conn.close()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Error initializing database: {e}")

# Add these routes if they don't exist

@app.route('/api/analytics')
def get_analytics():
    try:
        conn = sqlite3.connect('instance/restaurant.db')
        cursor = conn.cursor()
        
        # Get basic analytics
        cursor.execute('SELECT COUNT(*), SUM(total_amount) FROM completed_orders')
        result = cursor.fetchone()
        
        total_orders = result[0] or 0
        total_revenue = result[1] or 0
        avg_order_value = (total_revenue / total_orders) if total_orders > 0 else 0
        
        conn.close()
        
        return jsonify({
            'total_orders': total_orders,
            'total_revenue': round(total_revenue, 2),
            'avg_order_value': round(avg_order_value, 2)
        })
    except Exception as e:
        print(f"Analytics error: {e}")
        return jsonify({
            'total_orders': 0,
            'total_revenue': 0,
            'avg_order_value': 0
        })

if __name__ == '__main__':
    # Create database tables if they don't exist
    init_db()
    
    # Use environment variables for production
    debug_mode = os.getenv('FLASK_ENV') == 'development'
    
    if debug_mode:
        # Development mode
        socketio.run(app, debug=True, host='0.0.0.0', port=port)
    else:
        # Production mode
        socketio.run(app, debug=False, host='0.0.0.0', port=port)

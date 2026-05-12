from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date, timedelta
from functools import wraps
import json, os, csv, io

app = Flask(__name__)
app.secret_key = 'annettes-mart-secret-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///annettes_mart.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# =============================================================================
# MODELS
# =============================================================================

class User(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    username   = db.Column(db.String(50), unique=True, nullable=False)
    password   = db.Column(db.String(100), nullable=False)
    role       = db.Column(db.String(50), default='Cashier')
    status     = db.Column(db.String(20), default='Active')
    # JSON-encoded list of allowed section keys e.g. ["dashboard","sales"]
    # If NULL, no restriction (all sections allowed for Admin)
    permissions = db.Column(db.Text, nullable=True)


class Category(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(300))
    color       = db.Column(db.String(20), default='#2d6a4f')


class Product(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    sku         = db.Column(db.String(50))
    category    = db.Column(db.String(100))
    type        = db.Column(db.String(20), default='Both')
    buy_price   = db.Column(db.Float, default=0)
    sell_price  = db.Column(db.Float, default=0)
    wsell_price = db.Column(db.Float, default=0)
    stock       = db.Column(db.Integer, default=0)
    unit        = db.Column(db.String(30))
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True)


class Customer(db.Model):
    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(100), nullable=False)
    phone           = db.Column(db.String(30))
    email           = db.Column(db.String(100))
    type            = db.Column(db.String(20), default='Retail')
    address         = db.Column(db.String(200))
    total_purchases = db.Column(db.Float, default=0)
    credit_limit    = db.Column(db.Float, default=0)
    credit_used     = db.Column(db.Float, default=0)
    notes           = db.Column(db.Text)
    created_date    = db.Column(db.String(20))


class Supplier(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(200), nullable=False)
    contact  = db.Column(db.String(100))
    phone    = db.Column(db.String(30))
    email    = db.Column(db.String(100))
    address  = db.Column(db.String(300))
    products = db.Column(db.String(200))
    status   = db.Column(db.String(20), default='Active')
    notes    = db.Column(db.Text)
    total_supplied = db.Column(db.Float, default=0)


class Sale(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    date          = db.Column(db.String(20))
    customer      = db.Column(db.String(100), default='Walk-in')
    customer_id   = db.Column(db.Integer, nullable=True)
    type          = db.Column(db.String(20), default='Retail')
    subtotal      = db.Column(db.Float, default=0)
    discount      = db.Column(db.Float, default=0)
    discount_type = db.Column(db.String(10), default='percent')  # 'percent' or 'fixed'
    tax           = db.Column(db.Float, default=0)
    total         = db.Column(db.Float, default=0)
    cost          = db.Column(db.Float, default=0)
    payment_method = db.Column(db.String(30), default='Cash')
    amount_paid   = db.Column(db.Float, default=0)
    change_due    = db.Column(db.Float, default=0)
    notes         = db.Column(db.Text)
    items_json    = db.Column(db.Text, default='[]')
    status        = db.Column(db.String(20), default='Completed')  # Completed, Voided, Credit


class Purchase(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    date          = db.Column(db.String(20))
    supplier_id   = db.Column(db.Integer)
    supplier_name = db.Column(db.String(200))
    product_id    = db.Column(db.Integer)
    product_name  = db.Column(db.String(200))
    qty           = db.Column(db.Integer, default=0)
    unit_cost     = db.Column(db.Float, default=0)
    total         = db.Column(db.Float, default=0)
    status        = db.Column(db.String(20), default='Received')
    notes         = db.Column(db.Text)


class Expense(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    date        = db.Column(db.String(20))
    category    = db.Column(db.String(100))
    description = db.Column(db.String(300))
    amount      = db.Column(db.Float, default=0)
    payment_method = db.Column(db.String(30), default='Cash')
    notes       = db.Column(db.Text)


class Setting(db.Model):
    key   = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)


# =============================================================================
# HELPERS
# =============================================================================

def get_setting(key, default=''):
    s = Setting.query.get(key)
    return s.value if s else default

def set_setting(key, value):
    s = Setting.query.get(key)
    if s:
        s.value = str(value)
    else:
        db.session.add(Setting(key=key, value=str(value)))
    db.session.commit()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def permission_required(section):
    """Decorator to check if current user has access to a section."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'error': 'Unauthorized'}), 401
            user = User.query.get(session['user_id'])
            if not user:
                return jsonify({'error': 'Unauthorized'}), 401
            # Admin always has full access
            if user.role == 'Admin':
                return f(*args, **kwargs)
            if user.permissions:
                allowed = json.loads(user.permissions)
                if section not in allowed:
                    return jsonify({'error': 'Forbidden: insufficient permissions'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

def product_to_dict(p):
    return {
        'id': p.id, 'name': p.name, 'sku': p.sku or '', 'category': p.category or '',
        'type': p.type, 'buyPrice': p.buy_price, 'sellPrice': p.sell_price,
        'wsellPrice': p.wsell_price, 'stock': p.stock, 'unit': p.unit or '',
        'supplierId': p.supplier_id
    }

def customer_to_dict(c):
    return {
        'id': c.id, 'name': c.name, 'phone': c.phone or '', 'email': c.email or '',
        'type': c.type, 'address': c.address or '', 'totalPurchases': c.total_purchases or 0,
        'creditLimit': c.credit_limit or 0, 'creditUsed': c.credit_used or 0,
        'creditAvailable': max(0, (c.credit_limit or 0) - (c.credit_used or 0)),
        'notes': c.notes or '', 'createdDate': c.created_date or ''
    }

def supplier_to_dict(s):
    return {
        'id': s.id, 'name': s.name, 'contact': s.contact or '', 'phone': s.phone or '',
        'email': s.email or '', 'address': s.address or '', 'products': s.products or '',
        'status': s.status, 'notes': s.notes or '', 'totalSupplied': s.total_supplied or 0
    }

def sale_to_dict(s):
    return {
        'id': s.id, 'date': s.date, 'customer': s.customer, 'customerId': s.customer_id,
        'type': s.type, 'subtotal': s.subtotal, 'discount': s.discount,
        'discountType': s.discount_type or 'percent',
        'tax': s.tax or 0, 'total': s.total, 'cost': s.cost,
        'paymentMethod': s.payment_method or 'Cash',
        'amountPaid': s.amount_paid or 0, 'changeDue': s.change_due or 0,
        'notes': s.notes or '', 'status': s.status or 'Completed',
        'items': json.loads(s.items_json or '[]')
    }

def purchase_to_dict(p):
    return {
        'id': p.id, 'date': p.date, 'supplierId': p.supplier_id, 'supplierName': p.supplier_name or '',
        'productId': p.product_id, 'productName': p.product_name or '',
        'qty': p.qty, 'unitCost': p.unit_cost, 'total': p.total,
        'status': p.status, 'notes': p.notes or ''
    }

def expense_to_dict(e):
    return {
        'id': e.id, 'date': e.date, 'category': e.category or '',
        'description': e.description or '', 'amount': e.amount,
        'paymentMethod': e.payment_method or 'Cash', 'notes': e.notes or ''
    }

def category_to_dict(c):
    return {'id': c.id, 'name': c.name, 'description': c.description or '', 'color': c.color or '#2d6a4f'}


# =============================================================================
# SEED DATA
# =============================================================================

def seed_data():
    if User.query.count() == 0:
        db.session.add(User(
            name="Annette Owusu", username="admin",
            password="admin123", role="Admin", status="Active"
        ))
        db.session.commit()

    # Seed categories
    if Category.query.count() == 0:
        cats = [
            Category(name='Beverages', description='Drinks and liquids', color='#2d6a4f'),
            Category(name='Grains', description='Rice, flour, cereals', color='#f4a261'),
            Category(name='Dairy', description='Milk, cheese, eggs', color='#52b788'),
            Category(name='Snacks', description='Biscuits, chips, sweets', color='#e76f51'),
            Category(name='Personal Care', description='Hygiene and beauty', color='#264653'),
            Category(name='Cleaning', description='Detergents and cleaners', color='#2a9d8f'),
            Category(name='Condiments', description='Oils, sauces, spices', color='#e9c46a'),
            Category(name='Frozen', description='Frozen foods', color='#4cc9f0'),
            Category(name='Other', description='Miscellaneous items', color='#6b7280'),
        ]
        db.session.add_all(cats)
        db.session.commit()

    if Supplier.query.count() == 0:
        suppliers = [
            Supplier(name='Ghana Distributors Ltd', contact='Mr. Adu', phone='+233 24 500 0001',
                     email='gd@distrib.com', products='Beverages, Grains', status='Active'),
            Supplier(name='Accra Food Wholesalers', contact='Mrs. Serwaa', phone='+233 55 500 0002',
                     email='afw@food.com', products='Dairy, Frozen', status='Active'),
            Supplier(name='PZ Cussons Ghana', contact='Sales Dept', phone='+233 30 250 0003',
                     email='sales@pzcgh.com', products='Personal Care, Cleaning', status='Active'),
        ]
        db.session.add_all(suppliers)
        db.session.commit()

    if Product.query.count() == 0:
        products = [
            Product(name='Mineral Water 1.5L', sku='MW001', category='Beverages', type='Both',
                    buy_price=2.5, sell_price=3.5, wsell_price=3.0, stock=150, unit='pcs'),
            Product(name='Milo 400g', sku='ML001', category='Beverages', type='Both',
                    buy_price=18, sell_price=22, wsell_price=20, stock=80, unit='pcs'),
            Product(name='Rice 50kg Bag', sku='RC001', category='Grains', type='Wholesale',
                    buy_price=320, sell_price=380, wsell_price=350, stock=45, unit='bags'),
            Product(name='Cooking Oil 5L', sku='CO001', category='Condiments', type='Both',
                    buy_price=55, sell_price=70, wsell_price=62, stock=60, unit='pcs'),
            Product(name='Sugar 50kg', sku='SG001', category='Grains', type='Wholesale',
                    buy_price=280, sell_price=330, wsell_price=300, stock=8, unit='bags'),
            Product(name='Peak Milk 400g', sku='PM001', category='Dairy', type='Retail',
                    buy_price=28, sell_price=35, wsell_price=32, stock=5, unit='pcs'),
            Product(name='Pringles Original', sku='PR001', category='Snacks', type='Retail',
                    buy_price=25, sell_price=32, wsell_price=28, stock=40, unit='pcs'),
            Product(name='Morning Fresh 500ml', sku='MF001', category='Cleaning', type='Retail',
                    buy_price=12, sell_price=16, wsell_price=14, stock=90, unit='pcs'),
            Product(name='Omo Detergent 900g', sku='OM001', category='Cleaning', type='Both',
                    buy_price=22, sell_price=28, wsell_price=25, stock=3, unit='pcs'),
            Product(name='Close Up 100ml', sku='CU001', category='Personal Care', type='Retail',
                    buy_price=8, sell_price=12, wsell_price=10, stock=120, unit='pcs'),
        ]
        db.session.add_all(products)
        db.session.commit()

    if Customer.query.count() == 0:
        customers = [
            Customer(name='Kwame Asante', phone='+233 24 123 4567', email='kwame@email.com',
                     type='Wholesale', address='Tema', total_purchases=1450,
                     credit_limit=5000, credit_used=0, created_date=date.today().isoformat()),
            Customer(name='Abena Mensah', phone='+233 55 987 6543', email='',
                     type='Retail', address='Accra Central', total_purchases=340,
                     credit_limit=500, credit_used=0, created_date=date.today().isoformat()),
            Customer(name='Kofi Boateng', phone='+233 20 456 7890', email='kofi@biz.com',
                     type='Both', address='Kumasi', total_purchases=2800,
                     credit_limit=10000, credit_used=0, created_date=date.today().isoformat()),
        ]
        db.session.add_all(customers)
        db.session.commit()

    if Sale.query.count() == 0:
        import random
        products = Product.query.all()
        customers = Customer.query.all()
        today = date.today()
        for d_offset in range(6, -1, -1):
            sale_date = (today - timedelta(days=d_offset)).isoformat()
            for _ in range(random.randint(2, 5)):
                p = random.choice(products)
                qty = random.randint(1, 3)
                subtotal = p.sell_price * qty
                cost = p.buy_price * qty
                items = [{'productId': p.id, 'name': p.name, 'qty': qty,
                          'price': p.sell_price, 'cost': p.buy_price}]
                cust = random.choice(customers) if d_offset > 0 else None
                sale = Sale(
                    date=sale_date,
                    customer=cust.name if cust else 'Walk-in',
                    customer_id=cust.id if cust else None,
                    type='Wholesale' if p.type == 'Wholesale' else 'Retail',
                    subtotal=subtotal, discount=0, discount_type='percent',
                    tax=0, total=subtotal, cost=cost,
                    payment_method='Cash', amount_paid=subtotal, change_due=0,
                    status='Completed', items_json=json.dumps(items)
                )
                db.session.add(sale)
        db.session.commit()

    # Default settings
    defaults = {
        'name': "Annette's Mart",
        'address': '123 Market Street, Accra, Ghana',
        'phone': '+233 24 000 0000',
        'email': 'info@annettesmart.com',
        'currency': '₵',
        'lowstock': '10',
        'footer': "Thank you for shopping at Annette's Mart!",
        'tax_rate': '0',
        'tax_name': 'Tax',
        'invoice_prefix': 'INV',
        'theme_brand': '#1a3a2a',
        'theme_brand_mid': '#2d6a4f',
        'theme_brand_light': '#52b788',
        'theme_accent': '#f4a261',
        'db_type': 'sqlite',
        'system_name': "Annette's Mart",
        'system_tagline': 'Management System',
    }
    for k, v in defaults.items():
        if not Setting.query.get(k):
            db.session.add(Setting(key=k, value=v))
    db.session.commit()


# =============================================================================
# AUTH ROUTES
# =============================================================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    user = User.query.filter_by(
        username=data.get('username', ''),
        password=data.get('password', '')
    ).first()
    if user and user.status == 'Active':
        session['user_id']   = user.id
        session['user_name'] = user.name
        session['user_role'] = user.role
        perms = json.loads(user.permissions) if user.permissions else None
        return jsonify({
            'ok': True, 'name': user.name, 'role': user.role,
            'permissions': perms
        })
    return jsonify({'ok': False, 'error': 'Invalid credentials or inactive account'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/me')
def me():
    if 'user_id' not in session:
        return jsonify({'ok': False}), 401
    user = User.query.get(session['user_id'])
    if not user:
        return jsonify({'ok': False}), 401
    perms = json.loads(user.permissions) if user.permissions else None
    return jsonify({
        'ok': True,
        'name': session.get('user_name'),
        'role': session.get('user_role'),
        'permissions': perms
    })


# =============================================================================
# SETTINGS
# =============================================================================

@app.route('/api/settings', methods=['GET'])
@login_required
def get_settings():
    return jsonify({
        'name':            get_setting('name'),
        'address':         get_setting('address'),
        'phone':           get_setting('phone'),
        'email':           get_setting('email'),
        'currency':        get_setting('currency', '₵'),
        'lowstock':        int(get_setting('lowstock', '10')),
        'footer':          get_setting('footer'),
        'tax_rate':        float(get_setting('tax_rate', '0')),
        'tax_name':        get_setting('tax_name', 'Tax'),
        'invoice_prefix':  get_setting('invoice_prefix', 'INV'),
        'theme_brand':     get_setting('theme_brand', '#1a3a2a'),
        'theme_brand_mid': get_setting('theme_brand_mid', '#2d6a4f'),
        'theme_brand_light': get_setting('theme_brand_light', '#52b788'),
        'theme_accent':    get_setting('theme_accent', '#f4a261'),
        'db_type':         get_setting('db_type', 'sqlite'),
        'system_name':     get_setting('system_name', "Annette's Mart"),
        'system_tagline':  get_setting('system_tagline', 'Management System'),
    })

@app.route('/api/settings', methods=['POST'])
@login_required
def save_settings():
    data = request.json or {}
    keys = [
        'name', 'address', 'phone', 'email', 'currency', 'lowstock', 'footer',
        'tax_rate', 'tax_name', 'invoice_prefix',
        'theme_brand', 'theme_brand_mid', 'theme_brand_light', 'theme_accent',
        'db_type', 'system_name', 'system_tagline'
    ]
    for k in keys:
        if k in data:
            set_setting(k, data[k])
    return jsonify({'ok': True})


# =============================================================================
# CATEGORIES (CRUD)
# =============================================================================

@app.route('/api/categories', methods=['GET'])
@login_required
def get_categories():
    return jsonify([category_to_dict(c) for c in Category.query.order_by(Category.name).all()])

@app.route('/api/categories', methods=['POST'])
@login_required
def add_category():
    d = request.json or {}
    name = d.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name required'}), 400
    if Category.query.filter_by(name=name).first():
        return jsonify({'error': 'Category already exists'}), 409
    c = Category(name=name, description=d.get('description', ''), color=d.get('color', '#2d6a4f'))
    db.session.add(c)
    db.session.commit()
    return jsonify(category_to_dict(c)), 201

@app.route('/api/categories/<int:cid>', methods=['PUT'])
@login_required
def update_category(cid):
    c = Category.query.get_or_404(cid)
    d = request.json or {}
    new_name = d.get('name', c.name).strip()
    if new_name != c.name and Category.query.filter_by(name=new_name).first():
        return jsonify({'error': 'Category name already exists'}), 409
    c.name = new_name
    c.description = d.get('description', c.description)
    c.color = d.get('color', c.color)
    db.session.commit()
    return jsonify(category_to_dict(c))

@app.route('/api/categories/<int:cid>', methods=['DELETE'])
@login_required
def delete_category(cid):
    c = Category.query.get_or_404(cid)
    db.session.delete(c)
    db.session.commit()
    return jsonify({'ok': True})


# =============================================================================
# INVENTORY
# =============================================================================

@app.route('/api/inventory', methods=['GET'])
@login_required
def get_inventory():
    q   = request.args.get('q', '').lower()
    cat = request.args.get('category', '')
    query = Product.query
    if q:
        query = query.filter(
            db.or_(Product.name.ilike(f'%{q}%'), Product.sku.ilike(f'%{q}%'))
        )
    if cat:
        query = query.filter_by(category=cat)
    return jsonify([product_to_dict(p) for p in query.all()])

@app.route('/api/inventory', methods=['POST'])
@login_required
def add_product():
    d = request.json or {}
    if not d.get('name'):
        return jsonify({'error': 'Product name required'}), 400
    p = Product(
        name=d['name'], sku=d.get('sku', ''), category=d.get('category', 'Other'),
        type=d.get('type', 'Both'), buy_price=float(d.get('buyPrice', 0)),
        sell_price=float(d.get('sellPrice', 0)), wsell_price=float(d.get('wsellPrice', 0)),
        stock=int(d.get('stock', 0)), unit=d.get('unit', 'pcs'),
        supplier_id=d.get('supplierId') or None
    )
    db.session.add(p)
    db.session.commit()
    return jsonify(product_to_dict(p)), 201

@app.route('/api/inventory/<int:pid>', methods=['GET'])
@login_required
def get_product(pid):
    p = Product.query.get_or_404(pid)
    return jsonify(product_to_dict(p))

@app.route('/api/inventory/<int:pid>', methods=['PUT'])
@login_required
def update_product(pid):
    p = Product.query.get_or_404(pid)
    d = request.json or {}
    p.name        = d.get('name', p.name)
    p.sku         = d.get('sku', p.sku)
    p.category    = d.get('category', p.category)
    p.type        = d.get('type', p.type)
    p.buy_price   = float(d.get('buyPrice', p.buy_price))
    p.sell_price  = float(d.get('sellPrice', p.sell_price))
    p.wsell_price = float(d.get('wsellPrice', p.wsell_price))
    p.stock       = int(d.get('stock', p.stock))
    p.unit        = d.get('unit', p.unit)
    p.supplier_id = d.get('supplierId') or None
    db.session.commit()
    return jsonify(product_to_dict(p))

@app.route('/api/inventory/<int:pid>', methods=['DELETE'])
@login_required
def delete_product(pid):
    p = Product.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/inventory/bulk', methods=['POST'])
@login_required
def bulk_import_inventory():
    rows = request.json or []
    count = 0
    for row in rows:
        if row.get('name'):
            db.session.add(Product(
                name=row['name'], sku=row.get('sku', ''),
                category=row.get('category', 'Other'), type=row.get('type', 'Both'),
                buy_price=float(row.get('buyPrice', row.get('buy_price', 0))),
                sell_price=float(row.get('sellPrice', row.get('sell_price', 0))),
                wsell_price=float(row.get('wsellPrice', row.get('wsell_price', 0))),
                stock=int(float(row.get('stock', 0))), unit=row.get('unit', 'pcs')
            ))
            count += 1
    db.session.commit()
    return jsonify({'ok': True, 'imported': count})


# =============================================================================
# CUSTOMERS
# =============================================================================

@app.route('/api/customers', methods=['GET'])
@login_required
def get_customers():
    q = request.args.get('q', '').lower()
    query = Customer.query
    if q:
        query = query.filter(
            db.or_(Customer.name.ilike(f'%{q}%'), Customer.phone.ilike(f'%{q}%'))
        )
    return jsonify([customer_to_dict(c) for c in query.all()])

@app.route('/api/customers', methods=['POST'])
@login_required
def add_customer():
    d = request.json or {}
    if not d.get('name'):
        return jsonify({'error': 'Customer name required'}), 400
    c = Customer(
        name=d['name'], phone=d.get('phone', ''), email=d.get('email', ''),
        type=d.get('type', 'Retail'), address=d.get('address', ''),
        credit_limit=float(d.get('creditLimit', 0)),
        credit_used=float(d.get('creditUsed', 0)),
        notes=d.get('notes', ''),
        created_date=date.today().isoformat()
    )
    db.session.add(c)
    db.session.commit()
    return jsonify(customer_to_dict(c)), 201

@app.route('/api/customers/<int:cid>', methods=['GET'])
@login_required
def get_customer(cid):
    c = Customer.query.get_or_404(cid)
    data = customer_to_dict(c)
    # Attach purchase history
    sales = Sale.query.filter_by(customer_id=cid).order_by(Sale.id.desc()).all()
    data['purchases'] = [sale_to_dict(s) for s in sales]
    return jsonify(data)

@app.route('/api/customers/<int:cid>', methods=['PUT'])
@login_required
def update_customer(cid):
    c = Customer.query.get_or_404(cid)
    d = request.json or {}
    c.name         = d.get('name', c.name)
    c.phone        = d.get('phone', c.phone)
    c.email        = d.get('email', c.email)
    c.type         = d.get('type', c.type)
    c.address      = d.get('address', c.address)
    c.credit_limit = float(d.get('creditLimit', c.credit_limit or 0))
    c.credit_used  = float(d.get('creditUsed', c.credit_used or 0))
    c.notes        = d.get('notes', c.notes)
    db.session.commit()
    return jsonify(customer_to_dict(c))

@app.route('/api/customers/<int:cid>', methods=['DELETE'])
@login_required
def delete_customer(cid):
    c = Customer.query.get_or_404(cid)
    db.session.delete(c)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/customers/bulk', methods=['POST'])
@login_required
def bulk_import_customers():
    rows = request.json or []
    count = 0
    for row in rows:
        if row.get('name'):
            db.session.add(Customer(
                name=row['name'], phone=row.get('phone', ''),
                email=row.get('email', ''), type=row.get('type', 'Retail'),
                address=row.get('address', ''), created_date=date.today().isoformat()
            ))
            count += 1
    db.session.commit()
    return jsonify({'ok': True, 'imported': count})

@app.route('/api/customers/<int:cid>/pay-credit', methods=['POST'])
@login_required
def pay_credit(cid):
    c = Customer.query.get_or_404(cid)
    d = request.json or {}
    amount = float(d.get('amount', 0))
    if amount <= 0:
        return jsonify({'error': 'Invalid amount'}), 400
    c.credit_used = max(0, (c.credit_used or 0) - amount)
    db.session.commit()
    return jsonify(customer_to_dict(c))


# =============================================================================
# SUPPLIERS
# =============================================================================

@app.route('/api/suppliers', methods=['GET'])
@login_required
def get_suppliers():
    q = request.args.get('q', '').lower()
    query = Supplier.query
    if q:
        query = query.filter(Supplier.name.ilike(f'%{q}%'))
    return jsonify([supplier_to_dict(s) for s in query.all()])

@app.route('/api/suppliers', methods=['POST'])
@login_required
def add_supplier():
    d = request.json or {}
    if not d.get('name'):
        return jsonify({'error': 'Supplier name required'}), 400
    s = Supplier(
        name=d['name'], contact=d.get('contact', ''), phone=d.get('phone', ''),
        email=d.get('email', ''), address=d.get('address', ''),
        products=d.get('products', ''), status=d.get('status', 'Active'),
        notes=d.get('notes', '')
    )
    db.session.add(s)
    db.session.commit()
    return jsonify(supplier_to_dict(s)), 201

@app.route('/api/suppliers/<int:sid>', methods=['GET'])
@login_required
def get_supplier(sid):
    s = Supplier.query.get_or_404(sid)
    data = supplier_to_dict(s)
    # Attach purchase history
    purchases = Purchase.query.filter_by(supplier_id=sid).order_by(Purchase.id.desc()).all()
    data['purchases'] = [purchase_to_dict(p) for p in purchases]
    return jsonify(data)

@app.route('/api/suppliers/<int:sid>', methods=['PUT'])
@login_required
def update_supplier(sid):
    s = Supplier.query.get_or_404(sid)
    d = request.json or {}
    s.name     = d.get('name', s.name)
    s.contact  = d.get('contact', s.contact)
    s.phone    = d.get('phone', s.phone)
    s.email    = d.get('email', s.email)
    s.address  = d.get('address', s.address)
    s.products = d.get('products', s.products)
    s.status   = d.get('status', s.status)
    s.notes    = d.get('notes', s.notes)
    db.session.commit()
    return jsonify(supplier_to_dict(s))

@app.route('/api/suppliers/<int:sid>', methods=['DELETE'])
@login_required
def delete_supplier(sid):
    s = Supplier.query.get_or_404(sid)
    db.session.delete(s)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/suppliers/bulk', methods=['POST'])
@login_required
def bulk_import_suppliers():
    rows = request.json or []
    count = 0
    for row in rows:
        if row.get('name'):
            db.session.add(Supplier(
                name=row['name'], contact=row.get('contact', ''),
                phone=row.get('phone', ''), email=row.get('email', ''),
                products=row.get('products', ''), status=row.get('status', 'Active')
            ))
            count += 1
    db.session.commit()
    return jsonify({'ok': True, 'imported': count})


# =============================================================================
# SALES / POS
# =============================================================================

@app.route('/api/sales', methods=['GET'])
@login_required
def get_sales():
    q          = request.args.get('q', '').lower()
    date_from  = request.args.get('date_from', '')
    date_to    = request.args.get('date_to', '')
    sale_type  = request.args.get('type', '')
    status     = request.args.get('status', '')

    query = Sale.query.order_by(Sale.id.desc())
    if q:
        query = query.filter(
            db.or_(
                Sale.customer.ilike(f'%{q}%'),
                db.cast(Sale.id, db.String).ilike(f'%{q}%')
            )
        )
    if date_from:
        query = query.filter(Sale.date >= date_from)
    if date_to:
        query = query.filter(Sale.date <= date_to)
    if sale_type:
        query = query.filter_by(type=sale_type)
    if status:
        query = query.filter_by(status=status)

    return jsonify([sale_to_dict(s) for s in query.all()])

@app.route('/api/sales', methods=['POST'])
@login_required
def create_sale():
    d = request.json or {}
    items = d.get('items', [])
    if not items:
        return jsonify({'error': 'No items in sale'}), 400

    subtotal      = sum(float(i['price']) * int(i['qty']) for i in items)
    discount_type = d.get('discountType', 'percent')
    discount      = float(d.get('discount', 0))
    tax_rate      = float(d.get('tax', 0))
    payment_method = d.get('paymentMethod', 'Cash')

    if discount_type == 'fixed':
        after_discount = max(0, subtotal - discount)
    else:
        after_discount = subtotal * (1 - discount / 100)

    tax_amount = after_discount * (tax_rate / 100)
    total      = after_discount + tax_amount
    cost       = sum(float(i.get('cost', 0)) * int(i['qty']) for i in items)

    amount_paid = float(d.get('amountPaid', total))
    change_due  = max(0, amount_paid - total)
    sale_status = d.get('status', 'Completed')

    # Deduct stock
    for item in items:
        p = Product.query.get(item['productId'])
        if p:
            p.stock = max(0, p.stock - int(item['qty']))

    # Update customer
    cust_id   = d.get('customerId')
    cust_name = 'Walk-in'
    if cust_id:
        cust = Customer.query.get(cust_id)
        if cust:
            cust.total_purchases = (cust.total_purchases or 0) + total
            cust_name = cust.name
            if sale_status == 'Credit':
                cust.credit_used = (cust.credit_used or 0) + total

    prefix = get_setting('invoice_prefix', 'INV')
    sale = Sale(
        date=date.today().isoformat(),
        customer=cust_name, customer_id=cust_id,
        type=d.get('type', 'Retail'),
        subtotal=subtotal, discount=discount, discount_type=discount_type,
        tax=tax_amount, total=total, cost=cost,
        payment_method=payment_method, amount_paid=amount_paid, change_due=change_due,
        notes=d.get('notes', ''), status=sale_status,
        items_json=json.dumps(items)
    )
    db.session.add(sale)
    db.session.commit()

    result = sale_to_dict(sale)
    result['invoiceNumber'] = f"{prefix}-{sale.id:05d}"
    return jsonify(result), 201

@app.route('/api/sales/<int:sid>', methods=['GET'])
@login_required
def get_sale(sid):
    s = Sale.query.get_or_404(sid)
    result = sale_to_dict(s)
    prefix = get_setting('invoice_prefix', 'INV')
    result['invoiceNumber'] = f"{prefix}-{s.id:05d}"
    return jsonify(result)

@app.route('/api/sales/<int:sid>/void', methods=['POST'])
@login_required
def void_sale(sid):
    s = Sale.query.get_or_404(sid)
    if s.status == 'Voided':
        return jsonify({'error': 'Already voided'}), 400
    # Restore stock
    for item in json.loads(s.items_json or '[]'):
        p = Product.query.get(item.get('productId'))
        if p:
            p.stock += int(item.get('qty', 0))
    # Reverse customer totals
    if s.customer_id:
        cust = Customer.query.get(s.customer_id)
        if cust:
            cust.total_purchases = max(0, (cust.total_purchases or 0) - s.total)
            if s.status == 'Credit':
                cust.credit_used = max(0, (cust.credit_used or 0) - s.total)
    s.status = 'Voided'
    db.session.commit()
    return jsonify({'ok': True})


# =============================================================================
# PURCHASES
# =============================================================================

@app.route('/api/purchases', methods=['GET'])
@login_required
def get_purchases():
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')
    query = Purchase.query.order_by(Purchase.id.desc())
    if date_from:
        query = query.filter(Purchase.date >= date_from)
    if date_to:
        query = query.filter(Purchase.date <= date_to)
    return jsonify([purchase_to_dict(p) for p in query.all()])

@app.route('/api/purchases', methods=['POST'])
@login_required
def add_purchase():
    d = request.json or {}
    supp    = Supplier.query.get(d.get('supplierId'))
    prod    = Product.query.get(d.get('productId'))
    qty     = int(d.get('qty', 0))
    cost    = float(d.get('unitCost', 0))
    status  = d.get('status', 'Received')
    total   = qty * cost

    p = Purchase(
        date=d.get('date', date.today().isoformat()),
        supplier_id=d.get('supplierId'), supplier_name=supp.name if supp else '',
        product_id=d.get('productId'), product_name=prod.name if prod else '',
        qty=qty, unit_cost=cost, total=total, status=status,
        notes=d.get('notes', '')
    )

    if status == 'Received' and prod:
        prod.stock += qty
        prod.buy_price = cost  # update buy price to latest

    if supp:
        supp.total_supplied = (supp.total_supplied or 0) + total

    db.session.add(p)
    db.session.commit()
    return jsonify(purchase_to_dict(p)), 201

@app.route('/api/purchases/<int:pid>', methods=['PUT'])
@login_required
def update_purchase(pid):
    p = Purchase.query.get_or_404(pid)
    d = request.json or {}
    old_status = p.status
    new_status = d.get('status', p.status)

    # If status changes to Received and was not before, add stock
    if new_status == 'Received' and old_status != 'Received':
        prod = Product.query.get(p.product_id)
        if prod:
            prod.stock += p.qty

    p.status = new_status
    p.notes  = d.get('notes', p.notes)
    db.session.commit()
    return jsonify(purchase_to_dict(p))

@app.route('/api/purchases/<int:pid>', methods=['DELETE'])
@login_required
def delete_purchase(pid):
    p = Purchase.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    return jsonify({'ok': True})


# =============================================================================
# EXPENSES
# =============================================================================

@app.route('/api/expenses', methods=['GET'])
@login_required
def get_expenses():
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')
    category  = request.args.get('category', '')
    query = Expense.query.order_by(Expense.id.desc())
    if date_from:
        query = query.filter(Expense.date >= date_from)
    if date_to:
        query = query.filter(Expense.date <= date_to)
    if category:
        query = query.filter_by(category=category)
    return jsonify([expense_to_dict(e) for e in query.all()])

@app.route('/api/expenses', methods=['POST'])
@login_required
def add_expense():
    d = request.json or {}
    if not d.get('description') or not d.get('amount'):
        return jsonify({'error': 'Description and amount required'}), 400
    e = Expense(
        date=d.get('date', date.today().isoformat()),
        category=d.get('category', 'General'),
        description=d['description'],
        amount=float(d['amount']),
        payment_method=d.get('paymentMethod', 'Cash'),
        notes=d.get('notes', '')
    )
    db.session.add(e)
    db.session.commit()
    return jsonify(expense_to_dict(e)), 201

@app.route('/api/expenses/<int:eid>', methods=['PUT'])
@login_required
def update_expense(eid):
    e = Expense.query.get_or_404(eid)
    d = request.json or {}
    e.date           = d.get('date', e.date)
    e.category       = d.get('category', e.category)
    e.description    = d.get('description', e.description)
    e.amount         = float(d.get('amount', e.amount))
    e.payment_method = d.get('paymentMethod', e.payment_method)
    e.notes          = d.get('notes', e.notes)
    db.session.commit()
    return jsonify(expense_to_dict(e))

@app.route('/api/expenses/<int:eid>', methods=['DELETE'])
@login_required
def delete_expense(eid):
    e = Expense.query.get_or_404(eid)
    db.session.delete(e)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/expenses/categories', methods=['GET'])
@login_required
def get_expense_categories():
    cats = db.session.query(Expense.category).distinct().all()
    default_cats = ['Rent', 'Utilities', 'Salaries', 'Transport', 'Maintenance',
                    'Marketing', 'Supplies', 'Insurance', 'Taxes', 'General']
    existing = [c[0] for c in cats if c[0]]
    all_cats = sorted(set(default_cats + existing))
    return jsonify(all_cats)


# =============================================================================
# USERS & ROLES
# =============================================================================

ROLE_PERMISSIONS = {
    'Admin':       None,  # all access
    'Manager':     ['dashboard','inventory','sales','customers','suppliers','purchases','expenses','analytics','export','import'],
    'Cashier':     ['dashboard','sales','customers'],
    'Stock Keeper':['dashboard','inventory','purchases','suppliers'],
    'Accountant':  ['dashboard','analytics','expenses','export','sales'],
}

@app.route('/api/users', methods=['GET'])
@login_required
def get_users():
    users = User.query.all()
    return jsonify([{
        'id': u.id, 'name': u.name, 'username': u.username,
        'role': u.role, 'status': u.status,
        'permissions': json.loads(u.permissions) if u.permissions else None
    } for u in users])

@app.route('/api/users', methods=['POST'])
@login_required
def add_user():
    d = request.json or {}
    name     = d.get('name', '').strip()
    username = d.get('username', '').strip()
    password = d.get('password', '')
    role     = d.get('role', 'Cashier')
    if not name or not username or not password:
        return jsonify({'error': 'All fields required'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 409

    # Determine permissions
    custom_perms = d.get('permissions')  # list or None
    if custom_perms is not None:
        perms_json = json.dumps(custom_perms)
    elif role in ROLE_PERMISSIONS and ROLE_PERMISSIONS[role] is not None:
        perms_json = json.dumps(ROLE_PERMISSIONS[role])
    else:
        perms_json = None  # Admin: no restriction

    u = User(name=name, username=username, password=password, role=role,
             status=d.get('status', 'Active'), permissions=perms_json)
    db.session.add(u)
    db.session.commit()
    return jsonify({
        'id': u.id, 'name': u.name, 'username': u.username,
        'role': u.role, 'status': u.status,
        'permissions': json.loads(u.permissions) if u.permissions else None
    }), 201

@app.route('/api/users/<int:uid>', methods=['PUT'])
@login_required
def update_user(uid):
    u = User.query.get_or_404(uid)
    d = request.json or {}

    if 'name' in d:
        u.name = d['name']
    if 'role' in d:
        u.role = d['role']
        role = d['role']
        if d.get('permissions') is not None:
            u.permissions = json.dumps(d['permissions'])
        elif role in ROLE_PERMISSIONS and ROLE_PERMISSIONS[role] is not None:
            u.permissions = json.dumps(ROLE_PERMISSIONS[role])
        else:
            u.permissions = None
    if 'status' in d:
        u.status = d['status']
    if 'password' in d and d['password']:
        u.password = d['password']
    if 'permissions' in d and d['permissions'] is not None:
        u.permissions = json.dumps(d['permissions'])

    db.session.commit()
    return jsonify({
        'id': u.id, 'name': u.name, 'username': u.username,
        'role': u.role, 'status': u.status,
        'permissions': json.loads(u.permissions) if u.permissions else None
    })

@app.route('/api/users/<int:uid>', methods=['DELETE'])
@login_required
def delete_user(uid):
    if uid == 1:
        return jsonify({'error': 'Cannot delete main admin'}), 403
    u = User.query.get_or_404(uid)
    db.session.delete(u)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/roles', methods=['GET'])
@login_required
def get_roles():
    return jsonify([
        {'role': r, 'permissions': p}
        for r, p in ROLE_PERMISSIONS.items()
    ])


# =============================================================================
# DASHBOARD STATS
# =============================================================================

@app.route('/api/dashboard', methods=['GET'])
@login_required
def dashboard():
    today_str         = date.today().isoformat()
    month_str         = today_str[:7]
    lowstock_threshold = int(get_setting('lowstock', '10'))

    today_sales = Sale.query.filter_by(date=today_str).filter(Sale.status != 'Voided').all()
    month_sales = Sale.query.filter(
        Sale.date.startswith(month_str), Sale.status != 'Voided'
    ).all()

    today_total = sum(s.total for s in today_sales)
    month_total = sum(s.total for s in month_sales)

    low_stock  = Product.query.filter(Product.stock <= lowstock_threshold).all()
    recent     = Sale.query.order_by(Sale.id.desc()).limit(6).all()

    # Weekly trend
    weekly = []
    for i in range(6, -1, -1):
        d_str     = (date.today() - timedelta(days=i)).isoformat()
        day_sales = Sale.query.filter_by(date=d_str).filter(Sale.status != 'Voided').all()
        weekly.append({
            'label': datetime.strptime(d_str, '%Y-%m-%d').strftime('%a'),
            'total': sum(s.total for s in day_sales)
        })

    wholesale_total = sum(
        s.total for s in Sale.query.filter_by(type='Wholesale').filter(Sale.status != 'Voided').all()
    )
    retail_total = sum(
        s.total for s in Sale.query.filter_by(type='Retail').filter(Sale.status != 'Voided').all()
    )

    # Today's expenses
    today_expenses = sum(
        e.amount for e in Expense.query.filter_by(date=today_str).all()
    )
    month_expenses = sum(
        e.amount for e in Expense.query.filter(Expense.date.startswith(month_str)).all()
    )

    return jsonify({
        'todayTotal':    today_total,
        'todayCount':    len(today_sales),
        'monthTotal':    month_total,
        'productCount':  Product.query.count(),
        'lowStockCount': len(low_stock),
        'customerCount': Customer.query.count(),
        'todayExpenses': today_expenses,
        'monthExpenses': month_expenses,
        'recentSales':   [sale_to_dict(s) for s in recent],
        'lowStockItems': [{'id': p.id, 'name': p.name, 'stock': p.stock} for p in low_stock],
        'weekly':        weekly,
        'wholesaleTotal': wholesale_total,
        'retailTotal':   retail_total,
    })


# =============================================================================
# ANALYTICS / REPORTING
# =============================================================================

@app.route('/api/analytics', methods=['GET'])
@login_required
def analytics():
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')

    query = Sale.query.filter(Sale.status != 'Voided')
    if date_from:
        query = query.filter(Sale.date >= date_from)
    if date_to:
        query = query.filter(Sale.date <= date_to)
    all_sales = query.all()

    exp_query = Expense.query
    if date_from:
        exp_query = exp_query.filter(Expense.date >= date_from)
    if date_to:
        exp_query = exp_query.filter(Expense.date <= date_to)
    all_expenses = exp_query.all()

    total_rev   = sum(s.total for s in all_sales)
    total_cost  = sum(s.cost for s in all_sales)
    total_exp   = sum(e.amount for e in all_expenses)
    gross_profit = total_rev - total_cost
    net_profit   = gross_profit - total_exp
    margin       = (gross_profit / total_rev * 100) if total_rev else 0

    # Monthly (last 6 months)
    monthly = []
    for m in range(5, -1, -1):
        ref = date.today().replace(day=1)
        for _ in range(m):
            if ref.month == 1:
                ref = ref.replace(year=ref.year - 1, month=12)
            else:
                ref = ref.replace(month=ref.month - 1)
        key = ref.strftime('%Y-%m')
        ms  = [s for s in all_sales if s.date.startswith(key)]
        me  = [e for e in all_expenses if e.date.startswith(key)]
        monthly.append({
            'label':   ref.strftime('%b %y'),
            'revenue': sum(s.total for s in ms),
            'cost':    sum(s.cost for s in ms),
            'expenses': sum(e.amount for e in me),
        })

    # Category performance
    cat_map = {}
    for s in all_sales:
        for item in json.loads(s.items_json or '[]'):
            p   = Product.query.get(item.get('productId'))
            cat = p.category if p else 'Other'
            cat_map[cat] = cat_map.get(cat, 0) + float(item['price']) * int(item['qty'])

    # Top products
    prod_map = {}
    for s in all_sales:
        for item in json.loads(s.items_json or '[]'):
            pid = item.get('productId')
            if pid not in prod_map:
                prod_map[pid] = {'name': item.get('name', ''), 'qty': 0, 'rev': 0, 'cost': 0}
            prod_map[pid]['qty']  += int(item['qty'])
            prod_map[pid]['rev']  += float(item['price']) * int(item['qty'])
            prod_map[pid]['cost'] += float(item.get('cost', 0)) * int(item['qty'])
    for v in prod_map.values():
        v['profit'] = v['rev'] - v['cost']
    top = sorted(prod_map.values(), key=lambda x: x['rev'], reverse=True)[:10]

    # Payment method breakdown
    pay_map = {}
    for s in all_sales:
        pm = s.payment_method or 'Cash'
        pay_map[pm] = pay_map.get(pm, 0) + s.total

    # Expense by category
    exp_cat_map = {}
    for e in all_expenses:
        exp_cat_map[e.category] = exp_cat_map.get(e.category, 0) + e.amount

    return jsonify({
        'totalRevenue':  total_rev,
        'totalCost':     total_cost,
        'totalExpenses': total_exp,
        'grossProfit':   gross_profit,
        'netProfit':     net_profit,
        'margin':        margin,
        'monthly':       monthly,
        'categories':    [{'name': k, 'value': v} for k, v in cat_map.items()],
        'topProducts':   top,
        'paymentMethods': [{'name': k, 'value': v} for k, v in pay_map.items()],
        'expenseCategories': [{'name': k, 'value': v} for k, v in exp_cat_map.items()],
        'salesCount':    len(all_sales),
        'avgSaleValue':  (total_rev / len(all_sales)) if all_sales else 0,
    })

@app.route('/api/reports/sales-summary', methods=['GET'])
@login_required
def report_sales_summary():
    """Day-by-day sales report for a date range."""
    date_from = request.args.get('date_from', (date.today() - timedelta(days=30)).isoformat())
    date_to   = request.args.get('date_to', date.today().isoformat())
    sales = Sale.query.filter(
        Sale.date >= date_from, Sale.date <= date_to, Sale.status != 'Voided'
    ).order_by(Sale.date).all()

    by_day = {}
    for s in sales:
        if s.date not in by_day:
            by_day[s.date] = {'date': s.date, 'count': 0, 'revenue': 0, 'cost': 0, 'profit': 0}
        by_day[s.date]['count']   += 1
        by_day[s.date]['revenue'] += s.total
        by_day[s.date]['cost']    += s.cost
        by_day[s.date]['profit']  += (s.total - s.cost)

    return jsonify({
        'rows':      list(by_day.values()),
        'total_rev': sum(s.total for s in sales),
        'total_cost': sum(s.cost for s in sales),
        'total_count': len(sales),
    })

@app.route('/api/reports/inventory-valuation', methods=['GET'])
@login_required
def report_inventory_valuation():
    """Inventory valuation report."""
    products = Product.query.all()
    rows = []
    for p in products:
        rows.append({
            'id': p.id, 'name': p.name, 'category': p.category,
            'stock': p.stock, 'buyPrice': p.buy_price, 'sellPrice': p.sell_price,
            'costValue':  round(p.stock * p.buy_price, 2),
            'sellValue':  round(p.stock * p.sell_price, 2),
            'potentialProfit': round(p.stock * (p.sell_price - p.buy_price), 2),
        })
    total_cost_val = sum(r['costValue'] for r in rows)
    total_sell_val = sum(r['sellValue'] for r in rows)
    return jsonify({
        'rows': rows,
        'totalCostValue': total_cost_val,
        'totalSellValue': total_sell_val,
        'totalPotentialProfit': total_sell_val - total_cost_val,
    })

@app.route('/api/reports/expense-summary', methods=['GET'])
@login_required
def report_expense_summary():
    date_from = request.args.get('date_from', (date.today() - timedelta(days=30)).isoformat())
    date_to   = request.args.get('date_to', date.today().isoformat())
    expenses  = Expense.query.filter(
        Expense.date >= date_from, Expense.date <= date_to
    ).order_by(Expense.date).all()

    by_cat = {}
    for e in expenses:
        if e.category not in by_cat:
            by_cat[e.category] = {'category': e.category, 'count': 0, 'total': 0}
        by_cat[e.category]['count'] += 1
        by_cat[e.category]['total'] += e.amount

    return jsonify({
        'rows':  [expense_to_dict(e) for e in expenses],
        'byCategory': list(by_cat.values()),
        'total': sum(e.amount for e in expenses),
    })

@app.route('/api/reports/profit-loss', methods=['GET'])
@login_required
def report_profit_loss():
    date_from = request.args.get('date_from', (date.today() - timedelta(days=30)).isoformat())
    date_to   = request.args.get('date_to', date.today().isoformat())

    sales    = Sale.query.filter(Sale.date >= date_from, Sale.date <= date_to, Sale.status != 'Voided').all()
    expenses = Expense.query.filter(Expense.date >= date_from, Expense.date <= date_to).all()

    revenue      = sum(s.total for s in sales)
    cogs         = sum(s.cost for s in sales)
    gross_profit = revenue - cogs
    total_exp    = sum(e.amount for e in expenses)
    net_profit   = gross_profit - total_exp

    return jsonify({
        'dateFrom':     date_from,
        'dateTo':       date_to,
        'revenue':      revenue,
        'cogs':         cogs,
        'grossProfit':  gross_profit,
        'grossMargin':  (gross_profit / revenue * 100) if revenue else 0,
        'expenses':     total_exp,
        'netProfit':    net_profit,
        'netMargin':    (net_profit / revenue * 100) if revenue else 0,
        'salesCount':   len(sales),
        'expenseBreakdown': [expense_to_dict(e) for e in expenses],
    })


# =============================================================================
# DATA MANAGEMENT – EXPORT
# =============================================================================

@app.route('/api/export/<dtype>', methods=['GET'])
@login_required
def export_data(dtype):
    if dtype == 'inventory':
        data = [product_to_dict(p) for p in Product.query.all()]
    elif dtype == 'sales':
        data = [sale_to_dict(s) for s in Sale.query.all()]
    elif dtype == 'customers':
        data = [customer_to_dict(c) for c in Customer.query.all()]
    elif dtype == 'suppliers':
        data = [supplier_to_dict(s) for s in Supplier.query.all()]
    elif dtype == 'expenses':
        data = [expense_to_dict(e) for e in Expense.query.all()]
    elif dtype == 'purchases':
        data = [purchase_to_dict(p) for p in Purchase.query.all()]
    elif dtype == 'full':
        data = {
            'inventory':  [product_to_dict(p) for p in Product.query.all()],
            'sales':      [sale_to_dict(s) for s in Sale.query.all()],
            'customers':  [customer_to_dict(c) for c in Customer.query.all()],
            'suppliers':  [supplier_to_dict(s) for s in Supplier.query.all()],
            'expenses':   [expense_to_dict(e) for e in Expense.query.all()],
            'purchases':  [purchase_to_dict(p) for p in Purchase.query.all()],
            'categories': [category_to_dict(c) for c in Category.query.all()],
            'settings':   {s.key: s.value for s in Setting.query.all()},
            'exported_at': datetime.utcnow().isoformat(),
        }
    else:
        return jsonify({'error': 'Unknown export type'}), 400
    return jsonify(data)


# =============================================================================
# DATA MANAGEMENT – IMPORT (bulk endpoints already exist above)
# =============================================================================

@app.route('/api/import/full', methods=['POST'])
@login_required
def import_full():
    """Import a full JSON backup."""
    d = request.json or {}
    imported = {}

    if 'inventory' in d:
        count = 0
        for row in d['inventory']:
            if row.get('name'):
                db.session.add(Product(
                    name=row['name'], sku=row.get('sku', ''), category=row.get('category', 'Other'),
                    type=row.get('type', 'Both'),
                    buy_price=float(row.get('buyPrice', 0)), sell_price=float(row.get('sellPrice', 0)),
                    wsell_price=float(row.get('wsellPrice', 0)),
                    stock=int(float(row.get('stock', 0))), unit=row.get('unit', 'pcs')
                ))
                count += 1
        imported['inventory'] = count

    if 'customers' in d:
        count = 0
        for row in d['customers']:
            if row.get('name'):
                db.session.add(Customer(
                    name=row['name'], phone=row.get('phone', ''), email=row.get('email', ''),
                    type=row.get('type', 'Retail'), address=row.get('address', ''),
                    created_date=date.today().isoformat()
                ))
                count += 1
        imported['customers'] = count

    if 'suppliers' in d:
        count = 0
        for row in d['suppliers']:
            if row.get('name'):
                db.session.add(Supplier(
                    name=row['name'], contact=row.get('contact', ''), phone=row.get('phone', ''),
                    email=row.get('email', ''), products=row.get('products', ''),
                    status=row.get('status', 'Active')
                ))
                count += 1
        imported['suppliers'] = count

    db.session.commit()
    return jsonify({'ok': True, 'imported': imported})


# =============================================================================
# DATA MANAGEMENT – CLEAR / RESET
# =============================================================================

@app.route('/api/clear/<dtype>', methods=['DELETE'])
@login_required
def clear_data(dtype):
    if dtype == 'sales':
        Sale.query.delete()
    elif dtype == 'inventory':
        Product.query.delete()
    elif dtype == 'customers':
        Customer.query.delete()
    elif dtype == 'suppliers':
        Supplier.query.delete()
    elif dtype == 'expenses':
        Expense.query.delete()
    elif dtype == 'purchases':
        Purchase.query.delete()
    else:
        return jsonify({'error': 'Unknown type'}), 400
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/reset', methods=['DELETE'])
@login_required
def reset_all():
    for model in [Sale, Purchase, Product, Customer, Supplier, Expense, Category, Setting]:
        model.query.delete()
    User.query.filter(User.id != 1).delete()
    db.session.commit()
    seed_data()
    return jsonify({'ok': True})


# =============================================================================
# DATABASE CONNECTION SETTINGS (switch between SQLite / MySQL / PostgreSQL)
# =============================================================================

@app.route('/api/settings/db-test', methods=['POST'])
@login_required
def test_db_connection():
    """Test a database connection string without applying it."""
    d = request.json or {}
    db_type = d.get('dbType', 'sqlite')
    try:
        if db_type == 'sqlite':
            return jsonify({'ok': True, 'message': 'SQLite is always available.'})
        from sqlalchemy import create_engine, text
        if db_type == 'mysql':
            uri = (
                f"mysql+pymysql://{d.get('dbUser')}:{d.get('dbPass')}"
                f"@{d.get('dbHost', 'localhost')}:{d.get('dbPort', 3306)}/{d.get('dbName')}"
            )
        elif db_type == 'postgresql':
            uri = (
                f"postgresql://{d.get('dbUser')}:{d.get('dbPass')}"
                f"@{d.get('dbHost', 'localhost')}:{d.get('dbPort', 5432)}/{d.get('dbName')}"
            )
        else:
            return jsonify({'ok': False, 'message': 'Unknown database type'}), 400
        engine = create_engine(uri)
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        return jsonify({'ok': True, 'message': 'Connection successful!'})
    except Exception as ex:
        return jsonify({'ok': False, 'message': str(ex)}), 400


# =============================================================================
# INIT
# =============================================================================

with app.app_context():
    db.create_all()
    seed_data()

if __name__ == '__main__':
    app.run(debug=True, port=5000)

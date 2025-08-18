# =========================
# START OF APP.PY (Top)
# =========================

# 1️⃣ Eventlet monkey patch must be first
import eventlet
eventlet.monkey_patch()

# 2️⃣ Standard libraries
import os
import sys
import logging
import json
import traceback
import time
from datetime import datetime, timedelta, timezone

# 3️⃣ Load environment variables
from dotenv import load_dotenv
load_dotenv()

# 4️⃣ Flask & extensions
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, send_file, make_response, current_app
from extensions import db

from flask_migrate import Migrate
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from flask_babel import Babel, gettext as _
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

# =========================
# Flask App Configuration
# =========================
app = Flask(__name__)

# Secret key
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key')

# Instance folder for SQLite (fallback)
basedir = os.path.abspath(os.path.dirname(__file__))
instance_dir = os.path.join(basedir, 'instance')
os.makedirs(instance_dir, exist_ok=True)

# Default DB: SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(instance_dir, 'accounting_app.db')}"

# Override with production DB if available
_db_url = os.getenv('DATABASE_URL')
if _db_url:
    if _db_url.startswith('postgres://'):
        _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = _db_url

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Babel / i18n
app.config['BABEL_DEFAULT_LOCALE'] = os.getenv('BABEL_DEFAULT_LOCALE', 'en')
babel = Babel(app)
@app.errorhandler(500)
def handle_internal_error(e):
    try:
        if request.path.startswith('/api/'):
            return jsonify({'ok': False, 'error': 'Internal server error'}), 500
    except Exception:
        pass
    return e


# CSRF protection
csrf = CSRFProtect(app)

# Proxy fix (Render)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# API-friendly error handlers
from flask import jsonify, request

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    try:
        if request.path.startswith('/api/'):
            return jsonify({'ok': False, 'error': f'CSRF error: {getattr(e, "description", str(e))}'}), 400
    except Exception:
        pass
    return render_template('login.html', form=LoginForm()), 400

@app.errorhandler(500)
def handle_internal_error(e):
    try:
        if request.path.startswith('/api/'):
            return jsonify({'ok': False, 'error': 'Internal server error'}), 500
    except Exception:
        pass
    return e

# Initialize other extensions
db.init_app(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
bcrypt = Bcrypt(app)
socketio = SocketIO(app)

# Production-safe runtime schema patcher (avoid heavy migrations on legacy DB)
try:
    if os.getenv('RENDER') == 'true' or os.getenv('RENDER'):
        with app.app_context():
            from sqlalchemy import inspect as _sa_inspect, text as _sa_text
            _insp = _sa_inspect(db.engine)
            with db.engine.begin() as _conn:
                # 1) Ensure menu_categories table exists (idempotent)
                if 'menu_categories' not in _insp.get_table_names():
                    _conn.execute(_sa_text(
                        """
                        CREATE TABLE IF NOT EXISTS menu_categories (
                            id SERIAL PRIMARY KEY,
                            name VARCHAR(200) UNIQUE NOT NULL,
                            active BOOLEAN DEFAULT TRUE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    ))
                # 2) Ensure Settings receipt columns and logo_url exist (idempotent)
                if 'settings' in _insp.get_table_names():
                    existing_cols = {c['name'] for c in _insp.get_columns('settings')}
                    def addcol(col_sql):
                        _conn.execute(_sa_text(col_sql))
                    if 'receipt_paper_width' not in existing_cols:
                        addcol("ALTER TABLE settings ADD COLUMN IF NOT EXISTS receipt_paper_width VARCHAR(4)")
                    if 'receipt_margin_top_mm' not in existing_cols:
                        addcol("ALTER TABLE settings ADD COLUMN IF NOT EXISTS receipt_margin_top_mm INTEGER")
                    if 'receipt_margin_bottom_mm' not in existing_cols:
                        addcol("ALTER TABLE settings ADD COLUMN IF NOT EXISTS receipt_margin_bottom_mm INTEGER")
                    if 'receipt_margin_left_mm' not in existing_cols:
                        addcol("ALTER TABLE settings ADD COLUMN IF NOT EXISTS receipt_margin_left_mm INTEGER")
                    if 'receipt_margin_right_mm' not in existing_cols:
                        addcol("ALTER TABLE settings ADD COLUMN IF NOT EXISTS receipt_margin_right_mm INTEGER")
                    if 'receipt_font_size' not in existing_cols:
                        addcol("ALTER TABLE settings ADD COLUMN IF NOT EXISTS receipt_font_size INTEGER")
                    if 'receipt_show_logo' not in existing_cols:
                        addcol("ALTER TABLE settings ADD COLUMN IF NOT EXISTS receipt_show_logo BOOLEAN DEFAULT TRUE")
                    if 'receipt_show_tax_number' not in existing_cols:
                        addcol("ALTER TABLE settings ADD COLUMN IF NOT EXISTS receipt_show_tax_number BOOLEAN DEFAULT TRUE")
                    if 'receipt_footer_text' not in existing_cols:
                        addcol("ALTER TABLE settings ADD COLUMN IF NOT EXISTS receipt_footer_text VARCHAR(300)")
                    if 'logo_url' not in existing_cols:
                        addcol("ALTER TABLE settings ADD COLUMN IF NOT EXISTS logo_url VARCHAR(300)")
                # 3) Ensure customers table exists (idempotent)
                if 'customers' not in _insp.get_table_names():
                    _conn.execute(_sa_text(
                        """
                        CREATE TABLE IF NOT EXISTS customers (
                            id SERIAL PRIMARY KEY,
                            name VARCHAR(200) NOT NULL,
                            phone VARCHAR(50),
                            discount_percent NUMERIC(5,2) DEFAULT 0,
                            active BOOLEAN DEFAULT TRUE,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    ))
                # 4) Ensure sales_invoices.customer_phone exists (idempotent)
                if 'sales_invoices' in _insp.get_table_names():
                    existing_cols_si = {c['name'] for c in _insp.get_columns('sales_invoices')}
                    if 'customer_phone' not in existing_cols_si:
                        _conn.execute(_sa_text("ALTER TABLE sales_invoices ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(30)"))

                # 5) Ensure menu_items table exists
                if 'menu_items' not in _insp.get_table_names():
                    _conn.execute(_sa_text(
                        """
                        CREATE TABLE IF NOT EXISTS menu_items (
                            id SERIAL PRIMARY KEY,
                            category_id INTEGER NOT NULL REFERENCES menu_categories(id) ON DELETE CASCADE,
                            meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
                            price_override NUMERIC(12,2),
                            display_order INTEGER,
                            CONSTRAINT uq_category_meal UNIQUE (category_id, meal_id)
                        )
                        """
                    ))

except Exception as _patch_err:
    logging.error('Runtime schema patch failed: %s', _patch_err, exc_info=True)

# =========================
# END OF INITIALIZATION
# =========================

# Routes and rest of app.py remain unchanged

# Ensure SQLAlchemy track modifications disabled
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Babel / i18n
app.config['BABEL_DEFAULT_LOCALE'] = os.getenv('BABEL_DEFAULT_LOCALE', 'en')

from flask import session

login_manager.login_view = 'login'

# Basic error logging to file (errors only)
logging.basicConfig(filename='app.log', level=logging.ERROR, format='%(asctime)s %(levelname)s %(message)s')


def save_to_db(instance):
    try:
        db.session.add(instance)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logging.error('Database Error: %s', e, exc_info=True)
        return False



# Rate limiting for login attempts
login_attempts = {}  # { ip_address: {"count": int, "last_attempt": datetime} }

# Import models after db created
from models import User, Invoice, SalesInvoice, SalesInvoiceItem, Product, RawMaterial, Meal, MealIngredient, PurchaseInvoice, PurchaseInvoiceItem, ExpenseInvoice, ExpenseInvoiceItem, Employee, Salary, Payment, Account, LedgerEntry

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_locale():
    # language selection from query param, user pref, or accept headers
    lang = request.args.get('lang')
    if lang:
        return lang
    try:
        if current_user.is_authenticated:
            return getattr(current_user, 'language_pref', None) or app.config.get('BABEL_DEFAULT_LOCALE', 'ar')
    except Exception:
        pass
    return request.accept_languages.best_match(['ar', 'en']) or 'ar'
@app.context_processor
def inject_settings():
    try:
        from models import Settings
        s = Settings.query.first()
        return dict(settings=s)
    except Exception:
        return dict(settings=None)

@app.route('/toggle_theme', methods=['POST'])
@login_required
def toggle_theme():
    current = session.get('theme') or (getattr(inject_settings().get('settings'), 'default_theme', 'light'))
    session['theme'] = 'dark' if current != 'dark' else 'light'
    return redirect(request.referrer or url_for('dashboard'))

babel.init_app(app, locale_selector=get_locale)

# Make get_locale available in templates
@app.context_processor
def inject_conf_vars():
    return {
        'get_locale': get_locale
    }

@app.route('/')
def index():
    return redirect(url_for('login'))

# Safe url_for helper to avoid template crashes if an endpoint is missing in current deployment
@app.context_processor
def inject_safe_url():
    def safe_url(endpoint, **kwargs):
        try:
            return url_for(endpoint, **kwargs)
        except Exception:
            return None
    return dict(safe_url=safe_url)

# Safe Settings getter to avoid 500s if DB schema is outdated
def get_settings_safe():
    try:
        from models import Settings
        return Settings.query.first()
    except Exception:
        return None



from forms import LoginForm, SalesInvoiceForm, RawMaterialForm, MealForm, PurchaseInvoiceForm, ExpenseInvoiceForm, EmployeeForm, SalaryForm
# Register blueprints
try:
    from routes.vat import bp as vat_bp
    app.register_blueprint(vat_bp)
except Exception as _e:
    pass
# Register financials blueprint
try:
    from routes.financials import bp as financials_bp
    app.register_blueprint(financials_bp)
except Exception:
    pass



@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    client_ip = request.remote_addr

    # Check if blocked
    if client_ip in login_attempts:
        attempts_info = login_attempts[client_ip]
        if attempts_info["count"] >= 5 and datetime.now(timezone.utc) - attempts_info["last_attempt"] < timedelta(minutes=10):
            flash(_('Too many attempts. Try again later. / عدد المحاولات كبير، حاول لاحقاً.'), 'danger')
            return render_template('login.html', form=form)

    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
            if not user.active:
                flash(_('حسابك غير مفعل / Your account is not active.'), 'danger')
                return render_template('login.html', form=form)

            login_user(user, remember=form.remember.data)
            user.last_login()
            db.session.commit()
            login_attempts.pop(client_ip, None)  # reset attempts
            flash(_('تم تسجيل الدخول بنجاح / Logged in successfully.'), 'success')
            return redirect(url_for('dashboard'))

        # Wrong credentials — increment counter
        if client_ip not in login_attempts:
            login_attempts[client_ip] = {"count": 1, "last_attempt": datetime.now(timezone.utc)}
        else:
            login_attempts[client_ip]["count"] += 1
            login_attempts[client_ip]["last_attempt"] = datetime.now(timezone.utc)

        flash(_('اسم المستخدم أو كلمة المرور غير صحيحة / Invalid credentials.'), 'danger')

    return render_template('login.html', form=form)

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash(_('تم تسجيل الخروج / Logged out.'), 'info')
    return redirect(url_for('login'))

@app.route('/pos/<branch_code>')
@login_required
def pos_home(branch_code):
    # Minimal POS home to avoid template errors; integrate with real POS later
    if branch_code not in ('place_india','china_town'):
        flash(_('Unknown branch / فرع غير معروف'), 'danger')
        return redirect(url_for('dashboard'))
    return render_template('pos_home.html', branch_code=branch_code)

@app.route('/sales/<branch_code>', methods=['GET', 'POST'])
@login_required
def sales_branch(branch_code):
    # Validate branch
    if not is_valid_branch(branch_code):
        flash(_('Unknown branch / فرع غير معروف'), 'danger')
        return redirect(url_for('dashboard'))

    # Permissions: show page and create
    if request.method == 'POST' and not can_perm('sales','add', branch_scope=branch_code):
        flash(_('You do not have permission / لا تملك صلاحية الوصول'), 'danger')
        return redirect(url_for('sales_branch', branch_code=branch_code))
    if request.method == 'GET' and not can_perm('sales','view', branch_scope=branch_code):
        flash(_('You do not have permission / لا تملك صلاحية الوصول'), 'danger')
        return redirect(url_for('dashboard'))

    # Prepare meals
    meals = Meal.query.filter_by(active=True).all()
    product_choices = [(0, _('Select Meal / اختر الوجبة'))] + [(m.id, m.display_name) for m in meals]

    form = SalesInvoiceForm()
    # Force branch field to the fixed branch to satisfy validators and choices
    form.branch.data = branch_code
    for item_form in form.items:
        item_form.product_id.choices = product_choices

    # Prepare meals JSON for front-end helpers
    products_json = json.dumps([{
        'id': m.id,
        'name': m.display_name,
        'price_before_tax': float(m.selling_price)
    } for m in meals])

    # Default date
    if request.method == 'GET':
        form.date.data = datetime.now(timezone.utc).date()

    # Handle submit
    if form.validate_on_submit():
        # Generate invoice number
        last_invoice = SalesInvoice.query.filter_by(branch=branch_code).order_by(SalesInvoice.id.desc()).first()
        if last_invoice and last_invoice.invoice_number and '-' in last_invoice.invoice_number:
            try:
                last_num = int(last_invoice.invoice_number.split('-')[-1])
                invoice_number = f'SAL-{datetime.now(timezone.utc).year}-{last_num + 1:03d}'
            except Exception:
                invoice_number = f'SAL-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}'
        else:
            invoice_number = f'SAL-{datetime.now(timezone.utc).year}-001'

        # Totals
        total_before_tax = 0.0
        total_tax = 0.0
        total_discount = 0.0
        tax_rate = 0.15

        invoice = SalesInvoice(
            invoice_number=invoice_number,
            date=form.date.data,
            payment_method=form.payment_method.data,
            branch=branch_code,
            customer_name=form.customer_name.data,
            total_before_tax=0,
            tax_amount=0,
            discount_amount=0,
            total_after_tax_discount=0,
            status='unpaid',
            user_id=current_user.id
        )
        db.session.add(invoice)
        db.session.flush()

        for item_form in form.items.entries:
            if item_form.product_id.data and item_form.product_id.data != 0:
                meal = Meal.query.get(item_form.product_id.data)
                if meal:
                    qty = float(item_form.quantity.data)
                    discount_pct = float(item_form.discount.data or 0)
                    unit_price = float(meal.selling_price)
                    price_before_tax = unit_price * qty
                    tax = price_before_tax * tax_rate
                    discount_value = (price_before_tax + tax) * (discount_pct/100.0)
                    total_item = price_before_tax + tax - discount_value

                    total_before_tax += price_before_tax
                    total_tax += tax
                    total_discount += discount_value

                    inv_item = SalesInvoiceItem(
                        invoice_id=invoice.id,
                        product_name=meal.display_name,
                        quantity=qty,
                        price_before_tax=meal.selling_price,
                        tax=tax,
                        discount=discount_value,
                        total_price=total_item
                    )
                    db.session.add(inv_item)

        total_after_tax_discount = total_before_tax + total_tax - total_discount
        invoice.total_before_tax = total_before_tax
        invoice.tax_amount = total_tax
        invoice.discount_amount = total_discount
        invoice.total_after_tax_discount = total_after_tax_discount
        db.session.commit()

        # Emit and redirect on success
        socketio.emit('sales_update', {
            'invoice_number': invoice_number,
            'branch': branch_code,
            'total': float(total_after_tax_discount)
        })
        flash(_('Invoice created successfully / تم إنشاء الفاتورة بنجاح'), 'success')
        return redirect(url_for('sales_branch', branch_code=branch_code))

    # If POST but validation failed, show errors to help diagnose and stay on page
    if request.method == 'POST' and not form.validate():
        # Friendly message for common case: items invalid/missing
        if 'items' in (form.errors or {}):
            flash(_('Please complete invoice items (select meal and set quantity) / يرجى إكمال عناصر الفاتورة (اختر وجبة وحدد الكمية)'), 'danger')
        # Fallback: show top-level field errors
        try:
            for fname, errs in (form.errors or {}).items():
                # Skip items detailed dump to avoid noise
                if fname == 'items':
                    continue
                if not errs:
                    continue
                label = getattr(getattr(form, fname, None), 'label', None)
                label_text = label.text if label else fname
                flash(f"{label_text}: {', '.join([str(e) for e in errs])}", 'danger')
        except Exception:
            pass

    # List invoices for this branch only
    invoices = SalesInvoice.query.filter_by(branch=branch_code).order_by(SalesInvoice.date.desc()).all()
    return render_template('sales.html', form=form, invoices=invoices, products_json=products_json, fixed_branch=branch_code, branch_label=branch_label)

    return redirect(url_for('login'))

# Sales entry: Branch cards -> Tables -> Table invoice
@app.route('/sales', methods=['GET'])
@login_required
def sales():
    branches = [
        {'code': 'china_town', 'label': 'China Town', 'url': url_for('sales_tables', branch_code='china_town')},
        {'code': 'place_india', 'label': 'Place India', 'url': url_for('sales_tables', branch_code='place_india')},
    ]
    return render_template('sales_branches.html', branches=branches)

# Old unified sales screen kept under /sales/all for backward links
@app.route('/sales/all', methods=['GET', 'POST'])
@login_required
def sales_all():
    import json
    # Permissions: POST requires 'add'
    if request.method == 'POST' and not can_perm('sales','add'):
        flash(_('You do not have permission / لا تملك صلاحية الوصول'), 'danger')
        return redirect(url_for('sales'))

    # Get meals for dropdown (ready meals from cost management)
    meals = Meal.query.filter_by(active=True).all()
    product_choices = [(0, _('Select Meal / اختر الوجبة'))] + [(m.id, m.display_name) for m in meals]

    form = SalesInvoiceForm()

    # Set product choices for all item forms
    for item_form in form.items:
        item_form.product_id.choices = product_choices

    # Prepare meals JSON for JavaScript
    products_json = json.dumps([{
        'id': m.id,
        'name': m.display_name,
        'price_before_tax': float(m.selling_price)  # Use selling price from cost calculation
    } for m in meals])

    if form.validate_on_submit():
        # Generate invoice number
        last_invoice = SalesInvoice.query.order_by(SalesInvoice.id.desc()).first()
        if last_invoice and last_invoice.invoice_number and '-' in last_invoice.invoice_number:
            try:
                last_num = int(last_invoice.invoice_number.split('-')[-1])
                invoice_number = f'SAL-{datetime.now(timezone.utc).year}-{last_num + 1:03d}'
            except Exception:
                invoice_number = f'SAL-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}'
        else:
            invoice_number = f'SAL-{datetime.now(timezone.utc).year}-001'

# Seed default menu categories once (safe, best-effort)
MENU_SEEDED = False
@app.before_request
def _seed_menu_categories_once():
    global MENU_SEEDED
    if MENU_SEEDED:
        return
    try:
        from models import MenuCategory
        defaults = [
            'Appetizers','Soups','Salads','House Special','Prawns','Seafoods','Chinese Sizzling','Shaw Faw',
            'Chicken','Beef & Lamb','Rice & Biryani','Noodles & Chopsuey','Charcoal Grill / Kebabs',
            'Indian Delicacy (Chicken)','Indian Delicacy (Fish)','Indian Delicacy (Vegetables)','Juices','Soft Drink'
        ]
        existing = {c.name for c in MenuCategory.query.all()}
        to_add = [name for name in defaults if name not in existing]
        if to_add:
            for name in to_add:
                db.session.add(MenuCategory(name=name))
            db.session.commit()
    except Exception:
        # Table may not exist yet; ignore
        pass
    finally:
        MENU_SEEDED = True

# Helpers
BRANCH_CODES = {'china_town': 'China Town', 'place_india': 'Place India'}
PAYMENT_METHODS = ['CASH','MADA','VISA','MASTERCARD','BANK','AKS','GCC']

def is_valid_branch(code: str) -> bool:
    return code in BRANCH_CODES

@app.context_processor
def inject_globals():
    return dict(PAYMENT_METHODS=PAYMENT_METHODS, BRANCH_CODES=BRANCH_CODES)


@app.context_processor
def inject_csrf_token():
    try:
        from flask_wtf.csrf import generate_csrf
        return dict(csrf_token=generate_csrf)
    except Exception:
        return dict(csrf_token=lambda: '')

# Tables screen: 1..50 per branch
@app.route('/sales/<branch_code>/tables', methods=['GET'])
@login_required
def sales_tables(branch_code):
    if not is_valid_branch(branch_code):
        flash(_('Unknown branch / فرع غير معروف'), 'danger')
        return redirect(url_for('sales'))

    # Get table statuses and draft orders count
    from models import Table, DraftOrder
    table_statuses = {}
    draft_counts = {}

    existing_tables = Table.query.filter_by(branch_code=branch_code).all()
    for table in existing_tables:
        table_statuses[table.table_number] = table.status

    # Count active draft orders per table
    draft_orders = DraftOrder.query.filter_by(branch_code=branch_code, status='draft').all()
    for draft in draft_orders:
        draft_counts[draft.table_no] = draft_counts.get(draft.table_no, 0) + 1

    # Generate table list with status and draft count
    tables_data = []
    for n in range(1, 51):
        status = table_statuses.get(n, 'available')
        draft_count = draft_counts.get(n, 0)

        # Update status based on draft orders
        if draft_count > 0 and status == 'available':
            status = 'reserved'

        tables_data.append({
            'number': n,
            'status': status,
            'draft_count': draft_count
        })

    return render_template('sales_tables.html',
                         branch_code=branch_code,
                         branch_label=BRANCH_CODES[branch_code],
                         tables=tables_data)
# Table management screen: shows draft orders for a table
@app.route('/sales/<branch_code>/table/<int:table_no>/manage', methods=['GET'])
@login_required
def sales_table_manage(branch_code, table_no):
    if not is_valid_branch(branch_code) or table_no < 1 or table_no > 50:
        flash(_('Unknown branch/table / فرع أو طاولة غير معروف'), 'danger')
        return redirect(url_for('sales'))

    from models import DraftOrder, DraftOrderItem

    # Get all draft orders for this table
    draft_orders = DraftOrder.query.filter_by(
        branch_code=branch_code,
        table_no=table_no,
        status='draft'
    ).order_by(DraftOrder.created_at.desc()).all()

    # Calculate totals for each draft
    for draft in draft_orders:
        draft.total_amount = sum(float(item.total_price or 0) for item in draft.items)

    return render_template('sales_table_manage.html',
                         branch_code=branch_code,
                         branch_label=BRANCH_CODES[branch_code],
                         table_no=table_no,
                         draft_orders=draft_orders)

# Table invoice screen (split UI) - supports draft orders
@app.route('/sales/<branch_code>/table/<int:table_no>', methods=['GET'])
@login_required
def sales_table_invoice(branch_code, table_no):
    if not is_valid_branch(branch_code) or table_no < 1 or table_no > 50:
        flash(_('Unknown branch/table / فرع أو طاولة غير معروف'), 'danger')
        return redirect(url_for('sales'))

    import json
    from models import DraftOrder, DraftOrderItem

    # Check if we're editing an existing draft
    draft_id = request.args.get('draft_id', type=int)
    current_draft = None
    draft_items = []

    if draft_id:
        current_draft = DraftOrder.query.filter_by(
            id=draft_id,
            branch_code=branch_code,
            table_no=table_no,
            status='draft'
        ).first()
        if current_draft:
            draft_items = current_draft.items
    else:
        # Create new draft order
        current_draft = DraftOrder(
            branch_code=branch_code,
            table_no=table_no,
            user_id=current_user.id,
            status='draft'
        )
        db.session.add(current_draft)
        db.session.commit()
    # Load meals and categories (prefer MenuCategory if defined)
    try:
        meals = Meal.query.filter_by(active=True).all()
    except Exception as e:
        logging.error('Meals query failed: %s', e, exc_info=True)
        meals = []
    try:
        from models import MenuCategory
        cat_objs = MenuCategory.query.filter_by(active=True).order_by(MenuCategory.name.asc()).all()
        active_cats = [c.name for c in cat_objs]
        categories = active_cats if active_cats else sorted({(m.category or _('Uncategorized')) for m in meals})
        cat_map = {c.name: c.id for c in cat_objs}
    except Exception:
        categories = sorted({(m.category or _('Uncategorized')) for m in meals})
        cat_map = {}
    meals_data = [{
        'id': m.id,
        'name': m.display_name,
        'category': m.category or _('Uncategorized'),
        'price': float(m.selling_price or 0)
    } for m in meals]
    # VAT rate from settings if available
    settings = get_settings_safe()
    vat_rate = float(settings.vat_rate) if settings and settings.vat_rate is not None else 15.0
    from datetime import date as _date
    try:
        # Prepare draft items for the template
        draft_items_json = []
        if current_draft and draft_items:
            for item in draft_items:
                draft_items_json.append({
                    'id': item.id,
                    'meal_id': item.meal_id,
                    'name': item.product_name,
                    'quantity': float(item.quantity),
                    'price': float(item.price_before_tax),
                    'total': float(item.total_price)
                })

        return render_template('sales_table_invoice.html',
                               branch_code=branch_code,
                               branch_label=BRANCH_CODES[branch_code],
                               table_no=table_no,
                               current_draft=current_draft,
                               draft_items=json.dumps(draft_items_json),
                               categories=categories,
                               meals_json=json.dumps(meals_data),
                               cat_map_json=json.dumps(cat_map),
                               vat_rate=vat_rate,
                               today=_date.today().isoformat())
    except Exception as e:
        current_app.logger.error("=== Table View Error Traceback ===\n" + traceback.format_exc())
        return f"Error loading table: {e}", 500

# API: items by category
@app.route('/api/menu/<int:cat_id>/items')
@login_required
def api_menu_items(cat_id):
    from models import MenuItem, Meal
    items = MenuItem.query.filter_by(category_id=cat_id).order_by(MenuItem.display_order.asc().nulls_last()).all()
    res = []
    for it in items:
        price = float(it.price_override) if it.price_override is not None else float(it.meal.selling_price or 0)
        res.append({'id': it.id, 'meal_id': it.meal_id, 'name': it.meal.display_name, 'price': price})
    return jsonify(res)

    vat_rate = float(settings.vat_rate) if settings and settings.vat_rate is not None else 15.0
    from datetime import date as _date
    return render_template('sales_table_invoice.html',
                           branch_code=branch_code,
                           branch_label=BRANCH_CODES[branch_code],
                           table_no=table_no,
                           categories=categories,
                           meals_json=json.dumps(meals_data),
                           cat_map_json=json.dumps(cat_map),
                           vat_rate=vat_rate,
                           today=_date.today().isoformat())

# API: customer lookup by name or phone
@app.route('/api/customers/lookup')
@login_required
def api_customer_lookup():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify([])
    try:
        from models import Customer
        res = Customer.query.filter(
            (Customer.name.ilike(f"%{q}%")) | (Customer.phone.ilike(f"%{q}%"))
        ).order_by(Customer.name.asc()).limit(10).all()
        return jsonify([{'id': c.id, 'name': c.name, 'phone': c.phone, 'discount_percent': float(c.discount_percent or 0)} for c in res])
    except Exception:
        # If table doesn't exist yet, return empty
        return jsonify([])

# Customers management screen (simple CRUD)

# Defensive wrapper to prevent 500s on customers page while logging root cause
from functools import wraps

def _safe_customers_view(fn):
    @wraps(fn)
    def _inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as _fatal_err:
            logging.error('Customers view fatal error', exc_info=True)
            try:
                flash(_('Unexpected error in Customers page / حدث خطأ غير متوقع في شاشة العملاء'), 'danger')
            except Exception:
                pass
            # Render minimal page to avoid 500 while still letting user proceed
            try:
                return render_template('customers.html', customers=[]), 200
            except Exception:
                # ultimate fallback
                return redirect(url_for('dashboard'))
    return _inner

@app.route('/customers', methods=['GET','POST'])
@login_required
def customers():
    from models import Customer
    # Ensure table exists for legacy DBs
    try:
        Customer.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        pass
    # Add new customer
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        phone = (request.form.get('phone') or '').strip() or None
        try:
            discount_percent = float(request.form.get('discount_percent') or 0)
        except Exception:
            discount_percent = 0.0
        if not name:
            flash(_('Customer name is required / اسم العميل مطلوب'), 'danger')
        else:
            try:
                c = Customer(name=name, phone=phone, discount_percent=discount_percent, active=True)
                db.session.add(c)
                db.session.commit()
                flash(_('Customer added successfully / تم إضافة العميل بنجاح'), 'success')
            except Exception:
                db.session.rollback()
                flash(_('Failed to save customer / فشل حفظ العميل'), 'danger')
        return redirect(url_for('customers'))

    # List customers
    q = (request.args.get('q') or '').strip()
    query = Customer.query
    if q:
        query = query.filter((Customer.name.ilike(f"%{q}%")) | (Customer.phone.ilike(f"%{q}%")))
    try:
        customers = query.order_by(Customer.name.asc()).limit(200).all()
    except Exception:
        logging.error('Customers list failed', exc_info=True)
        customers = []
        try:
            flash(_('Customers storage is not ready yet. Please import or add customers. / مخزن العملاء غير جاهز بعد. يرجى إضافة أو استيراد عملاء.'), 'warning')
        except Exception:
            pass
    return render_template('customers.html', customers=customers, q=q)

@app.route('/customers/<int:cid>/edit', methods=['GET','POST'])
@login_required
def customers_edit(cid):
    from models import Customer
    c = Customer.query.get_or_404(cid)
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        phone = (request.form.get('phone') or '').strip() or None
        try:
            discount_percent = float(request.form.get('discount_percent') or 0)
        except Exception:
            discount_percent = 0.0
        if not name:
            flash(_('Customer name is required / اسم العميل مطلوب'), 'danger')
        else:
            try:
                c.name = name; c.phone = phone; c.discount_percent = discount_percent
                db.session.commit()
                flash(_('Customer updated / تم تحديث العميل'), 'success')
                return redirect(url_for('customers'))
            except Exception:
                db.session.rollback()
                flash(_('Failed to update customer / تعذر تحديث العميل'), 'danger')
    return render_template('customers_edit.html', c=c)

@app.route('/customers/<int:cid>/delete', methods=['POST'])
@login_required
def customers_delete(cid):
    from models import Customer
    c = Customer.query.get_or_404(cid)
    try:
        db.session.delete(c)
        db.session.commit()
        flash(_('Customer deleted / تم حذف العميل'), 'success')
    except Exception:
        db.session.rollback()
        flash(_('Failed to delete customer / تعذر حذف العميل'), 'danger')
    return redirect(url_for('customers'))

@app.route('/customers/<int:cid>/toggle', methods=['POST'])
@login_required
def customers_toggle(cid):
    from models import Customer
    c = Customer.query.get_or_404(cid)
    c.active = not bool(c.active)
    db.session.commit()
    flash(_('Customer status updated / تم تحديث حالة العميل'), 'success')
    return redirect(url_for('customers'))

@app.route('/customers/import/csv', methods=['POST'])
@login_required
def customers_import_csv():
    from models import Customer
    file = request.files.get('file')
    if not file or file.filename.strip() == '':
        flash(_('Please choose a CSV file / يرجى اختيار ملف CSV'), 'danger')
        return redirect(url_for('customers'))
    import csv, io
    try:
        raw = file.read()
        text = raw.decode('utf-8-sig', errors='ignore')
        f = io.StringIO(text)
        reader = csv.DictReader(f)
        added = 0
        for row in reader:
            name = (row.get('name') or row.get('Name') or '').strip()
            phone = (row.get('phone') or row.get('Phone') or '').strip() or None
            try:
                dp = float((row.get('discount_percent') or row.get('Discount') or 0) or 0)
            except Exception:
                dp = 0.0
            if not name:
                continue
            db.session.add(Customer(name=name, phone=phone, discount_percent=dp, active=True))
            added += 1
        db.session.commit()
        flash(_('%(n)s customers imported / تم استيراد %(n)s عميل', n=added), 'success')
    except Exception:
        db.session.rollback()
        flash(_('Invalid CSV format / تنسيق CSV غير صالح'), 'danger')
    return redirect(url_for('customers'))

@app.route('/customers/import/excel', methods=['POST'])
@login_required
def customers_import_excel():
    # Stub: Excel import requires additional dependencies (e.g., openpyxl/pandas)
    flash(_('Excel import not enabled on this deployment. Please use CSV. / استيراد Excel غير مفعّل حالياً، يرجى استخدام CSV'), 'warning')
    return redirect(url_for('customers'))

@app.route('/customers/import/pdf', methods=['POST'])
@login_required
def customers_import_pdf():
    # Stub: PDF parsing is not supported without additional libs; recommend CSV
    flash(_('PDF import not enabled. Please use CSV. / استيراد PDF غير مفعّل، يرجى استخدام CSV'), 'warning')
    return redirect(url_for('customers'))

@app.route('/customers/export.csv')
@login_required
def customers_export_csv():
    from models import Customer
    import csv, io
    buf = io.StringIO(); writer = csv.writer(buf)
    writer.writerow(['name','phone','discount_percent','active','created_at'])
    for c in Customer.query.order_by(Customer.name.asc()).all():
        writer.writerow([c.name, c.phone or '', float(c.discount_percent or 0), int(bool(c.active)), (c.created_at or '')])
    resp = make_response(buf.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename=customers.csv'
    return resp

# Menu categories (simple admin)
@app.route('/menu', methods=['GET','POST'])
@login_required
def menu():
    from models import MenuCategory
    # Create
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        if not name:
            flash(_('Category name is required / اسم القسم مطلوب'), 'danger')
        else:
            # Ensure unique
            exists = MenuCategory.query.filter_by(name=name).first()
            if exists:
                flash(_('Category already exists / القسم موجود مسبقاً'), 'warning')
            else:
                cat = MenuCategory(name=name, active=True)
                db.session.add(cat)
                db.session.commit()
                flash(_('Category added / تم إضافة القسم'), 'success')
        return redirect(url_for('menu'))
    # List + optional items management
    from models import MenuItem, Meal
    cats = MenuCategory.query.order_by(MenuCategory.name.asc()).all()
    sel_id = request.args.get('cat_id', type=int)
    selected_category = None
    items = []
    meals = []
    try:
        meals = Meal.query.filter_by(active=True).order_by(Meal.name.asc()).all()
    except Exception:
        meals = []
    if sel_id:
        selected_category = MenuCategory.query.get(sel_id)
        if selected_category:
            try:
                items = MenuItem.query.filter_by(category_id=sel_id).order_by(MenuItem.display_order.asc().nulls_last()).all()
            except Exception:
                items = []
    return render_template('menu_simple.html', categories=cats, selected_category=selected_category, items=items, meals=meals)

# Menu items management (link meals to categories)
@app.route('/menu/item/add', methods=['POST'])
@login_required
def menu_item_add():
    from models import MenuItem, MenuCategory, Meal
    try:
        section_id = int(request.form.get('section_id') or 0)
        meal_id = int(request.form.get('meal_id') or 0)
        price_override = request.form.get('price_override')
        display_order = request.form.get('display_order')
        if price_override == '' or price_override is None:
            price_override = None
        else:
            price_override = float(price_override)
        display_order = int(display_order) if (display_order or '').strip() else None
        # Validate
        if not MenuCategory.query.get(section_id) or not Meal.query.get(meal_id):
            flash(_('Invalid section or meal'), 'danger')
            return redirect(url_for('menu', cat_id=section_id))
        # Upsert unique (section, meal)
        ex = MenuItem.query.filter_by(category_id=section_id, meal_id=meal_id).first()
        if ex:
            ex.price_override = price_override
            ex.display_order = display_order
        else:
            db.session.add(MenuItem(category_id=section_id, meal_id=meal_id, price_override=price_override, display_order=display_order))
        db.session.commit()
        flash(_('Item saved'), 'success')
    except Exception as e:
        db.session.rollback()
        flash(_('Failed to save item'), 'danger')
    return redirect(url_for('menu'))

@app.route('/menu/item/<int:item_id>/update', methods=['POST'])
@login_required
def menu_item_update(item_id):
    from models import MenuItem
    it = MenuItem.query.get_or_404(item_id)
    try:
        price_override = request.form.get('price_override')
        display_order = request.form.get('display_order')
        it.price_override = (None if price_override == '' else float(price_override))
        it.display_order = int(display_order) if (display_order or '').strip() else None
        db.session.commit()
        flash(_('Item updated'), 'success')
    except Exception:
        db.session.rollback()
        flash(_('Update failed'), 'danger')
    return redirect(url_for('menu'))

@app.route('/menu/item/<int:item_id>/delete', methods=['POST'])
@login_required
def menu_item_delete(item_id):
    from models import MenuItem
# API: sales void password check
@app.route('/api/sales/void-check', methods=['POST'])
@login_required
def api_sales_void_check():
    try:
        data = request.get_json(silent=True) or {}
        pwd = (data.get('password') or '').strip()
        # Determine expected password from settings, fall back to '0000'
        settings = get_settings_safe()
        expected = None
        if settings and getattr(settings, 'void_password', None):
            expected = str(settings.void_password)
        elif settings and getattr(settings, 'tax_number', None):
            expected = str(settings.tax_number)
        else:
            expected = '0000'
        if pwd == str(expected):
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': 'Wrong password'}), 400
    except Exception as e:
        current_app.logger.error("=== Void Check Error Traceback ===\n" + traceback.format_exc())
        return jsonify({'ok': False, 'error': str(e)}), 500

    it = MenuItem.query.get_or_404(item_id)
    try:
        db.session.delete(it)
        db.session.commit()
        flash(_('Item deleted'), 'success')
    except Exception:
        db.session.rollback()
        flash(_('Delete failed'), 'danger')
    return redirect(url_for('menu'))


@app.route('/menu/<int:cat_id>/toggle', methods=['POST'])
@login_required
def menu_toggle(cat_id):
    from models import MenuCategory
    cat = MenuCategory.query.get_or_404(cat_id)
    cat.active = not bool(cat.active)
    db.session.commit()
    flash(_('Category status updated / تم تحديث حالة القسم'), 'success')
    return redirect(url_for('menu'))

# Checkout API: create invoice + items + payment, then return receipt URL

@csrf.exempt
@app.route('/api/sales/checkout', methods=['POST'])
@login_required
def api_sales_checkout():
    # Live logic: remove debug echo and proceed to real invoice creation

    try:
        from datetime import datetime as _dt
        data = request.get_json(silent=True) or {}
        branch_code = data.get('branch_code')
        table_no = int(data.get('table_no') or 0)
        items = data.get('items') or []  # [{meal_id, qty}]
        customer_name = data.get('customer_name') or None
        customer_phone = data.get('customer_phone') or None
        discount_pct = float(data.get('discount_pct') or 0)
        tax_pct = float(data.get('tax_pct') or 15)
        payment_method = data.get('payment_method') or 'CASH'

        if not is_valid_branch(branch_code) or not items:
            return jsonify({'ok': False, 'error': 'Invalid branch or empty items'}), 400

        # Ensure tables exist
        try:
            db.create_all()
        except Exception:
            pass

        # Generate invoice number SAL-YYYY-###
        last = SalesInvoice.query.order_by(SalesInvoice.id.desc()).first()
        if last and last.invoice_number and '-' in last.invoice_number:
            try:
                last_num = int(str(last.invoice_number).split('-')[-1])
                new_num = last_num + 1
            except Exception:
                new_num = 1
        else:
            new_num = 1

        # Get current datetime in Saudi Arabia timezone (UTC+3)
        try:
            from datetime import timezone as _tz
            saudi_tz = _tz(timedelta(hours=3))
            _now = _dt.now(saudi_tz)
        except Exception:
            _now = _dt.now()

        invoice_number = f"SAL-{_now.year}-{new_num:03d}"

        # Calculate totals and build items
        subtotal = 0.0
        tax_total = 0.0
        invoice_items = []
        for it in items:
            meal = Meal.query.get(int(it.get('meal_id')))
            qty = float(it.get('qty') or 0)
            if not meal or qty <= 0:
                continue
            unit = float(meal.selling_price or 0)
            line_sub = unit * qty
            line_tax = line_sub * (tax_pct / 100.0)
            subtotal += line_sub
            tax_total += line_tax
            total_line = line_sub + line_tax
            invoice_items.append({
                'name': meal.display_name,
                'qty': qty,
                'price_before_tax': unit,
                'tax': line_tax,
                'total': total_line
            })

        discount_val = (subtotal + tax_total) * (discount_pct / 100.0)
        grand_total = (subtotal + tax_total) - discount_val

        # Persist invoice
        inv = SalesInvoice(
            invoice_number=invoice_number,
            date=_now.date(),
            payment_method=payment_method,
            branch=branch_code,
            table_no=table_no,
            customer_name=customer_name,
            customer_phone=customer_phone,
            total_before_tax=subtotal,
            tax_amount=tax_total,
            discount_amount=discount_val,
            total_after_tax_discount=grand_total,
            status='paid',
            user_id=current_user.id
        )

        try:
            db.session.add(inv)
            db.session.flush()

            # Update table status to occupied when order is created
            from models import Table
            table = Table.query.filter_by(branch_code=branch_code, table_number=table_no).first()
            if not table:
                table = Table(branch_code=branch_code, table_number=table_no, status='occupied', current_order_id=inv.id)
                db.session.add(table)
            else:
                table.status = 'occupied'
                table.current_order_id = inv.id
                table.updated_at = _now

        except Exception as e:
            db.session.rollback()
            logging.exception('checkout flush failed')
            return jsonify({'ok': False, 'error': str(e)}), 500

        for it in invoice_items:
            db.session.add(SalesInvoiceItem(
                invoice_id=inv.id,
                product_name=str(it.get('name') or ''),
                quantity=float(it.get('qty') or 0),
                price_before_tax=float(it.get('price_before_tax') or 0),
                tax=float(it.get('tax') or 0),
                discount=0,
                total_price=float(it.get('total') or 0)
            ))

        # Record payment
        db.session.add(Payment(
            invoice_id=inv.id,
            invoice_type='sales',
            amount_paid=grand_total,
            payment_method=payment_method
        ))

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logging.exception('checkout commit failed')
            return jsonify({'ok': False, 'error': str(e)}), 500

        receipt_url = url_for('sales_receipt', invoice_id=inv.id)
        return jsonify({'ok': True, 'invoice_id': inv.id, 'print_url': receipt_url})

    except Exception as e:
        logging.exception('checkout top-level failed')
        return jsonify({'ok': False, 'error': str(e)}), 500


# Receipt (80mm thermal style)
@app.route('/sales/receipt/<int:invoice_id>')
@login_required
def sales_receipt(invoice_id):
    invoice = SalesInvoice.query.get_or_404(invoice_id)
    items = SalesInvoiceItem.query.filter_by(invoice_id=invoice_id).all()
    settings = get_settings_safe()
    return render_template('sales_receipt.html', invoice=invoice, items=items, settings=settings)


@app.route('/purchases', methods=['GET', 'POST'])
@login_required
def purchases():
    import json

    # Get raw materials for dropdown
    raw_materials = RawMaterial.query.filter_by(active=True).all()
    material_choices = [(0, _('Select Raw Material / اختر المادة الخام'))] + [(m.id, m.display_name) for m in raw_materials]

    form = PurchaseInvoiceForm()

    # Set material choices for all item forms
    for item_form in form.items:
        item_form.raw_material_id.choices = material_choices

    # Prepare materials JSON for JavaScript
    materials_json = json.dumps([{
        'id': m.id,
        'name': m.display_name,
        'cost_per_unit': float(m.cost_per_unit),
        'unit': m.unit,
        'stock_quantity': float(m.stock_quantity)
    } for m in raw_materials])

    if form.validate_on_submit():
        # Generate invoice number
        last_invoice = PurchaseInvoice.query.order_by(PurchaseInvoice.id.desc()).first()
        if last_invoice and last_invoice.invoice_number and '-' in last_invoice.invoice_number:
            try:
                last_num = int(last_invoice.invoice_number.split('-')[-1])
                invoice_number = f'PUR-{datetime.now(timezone.utc).year}-{last_num + 1:03d}'
            except Exception:
                invoice_number = f'PUR-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}'
        else:
            invoice_number = f'PUR-{datetime.now(timezone.utc).year}-001'

        # Calculate totals
        total_before_tax = 0
        total_tax = 0
        total_discount = 0
        tax_rate = 0.15

        # Create invoice
        invoice = PurchaseInvoice(
            invoice_number=invoice_number,
            date=form.date.data,
            supplier_name=form.supplier_name.data,
            payment_method=form.payment_method.data,
            total_before_tax=0,  # Will be calculated
            tax_amount=0,  # Will be calculated
            discount_amount=0,  # Will be calculated
            total_after_tax_discount=0,  # Will be calculated
            status='unpaid',
            user_id=current_user.id
        )
        db.session.add(invoice)
        db.session.flush()

        # Add invoice items and update stock
        for item_form in form.items.entries:
            if item_form.raw_material_id.data and item_form.raw_material_id.data != 0:  # Valid material selected
                raw_material = RawMaterial.query.get(item_form.raw_material_id.data)
                if raw_material:
                    qty = float(item_form.quantity.data)
                    unit_price = float(item_form.price_before_tax.data)
                    discount_pct = float(item_form.discount.data or 0)  # percent

                    # Calculate amounts
                    price_before_tax = unit_price * qty
                    tax = price_before_tax * tax_rate
                    discount = (price_before_tax + tax) * (discount_pct/100.0)
                    total_item = price_before_tax + tax - discount

                    # Add to invoice totals
                    total_before_tax += price_before_tax
                    total_tax += tax
                    total_discount += discount

                    # Update raw material stock quantity
                    raw_material.stock_quantity += qty

                    # Update cost per unit (weighted average)
                    if raw_material.stock_quantity > 0:
                        old_total_cost = float(raw_material.cost_per_unit) * (float(raw_material.stock_quantity) - qty)
                        new_total_cost = old_total_cost + (unit_price * qty)
                        raw_material.cost_per_unit = new_total_cost / float(raw_material.stock_quantity)

                    # Create invoice item
                    inv_item = PurchaseInvoiceItem(
                        invoice_id=invoice.id,
                        raw_material_id=raw_material.id,
                        raw_material_name=raw_material.display_name,
                        quantity=qty,
                        price_before_tax=unit_price,
                        tax=tax,
                        discount=discount,
                        total_price=total_item
                    )
                    db.session.add(inv_item)


        # Update invoice totals
        total_after_tax_discount = total_before_tax + total_tax - total_discount
        invoice.total_before_tax = total_before_tax
        invoice.tax_amount = total_tax
        invoice.discount_amount = total_discount
        invoice.total_after_tax_discount = total_after_tax_discount
        # Update invoice totals
        total_after_tax_discount = total_before_tax + total_tax - total_discount
        invoice.total_before_tax = total_before_tax
        invoice.tax_amount = total_tax
        invoice.discount_amount = total_discount
        invoice.total_after_tax_discount = total_after_tax_discount

        db.session.commit()

        # Post to ledger (Inventory, VAT Input, Cash/AP)
        try:
            def get_or_create(code, name, type_):
                acc = Account.query.filter_by(code=code).first()
                if not acc:
                    acc = Account(code=code, name=name, type=type_)
                    db.session.add(acc)
                    db.session.flush()
                return acc
            inv_acc = get_or_create('1200', 'Inventory', 'ASSET')
            vat_in_acc = get_or_create('1300', 'VAT Input', 'ASSET')
            cash_acc = get_or_create('1000', 'Cash', 'ASSET')
            ap_acc = get_or_create('2000', 'Accounts Payable', 'LIABILITY')

            settle_cash_like = ['CASH','MADA','VISA','MASTERCARD','BANK','AKS','GCC','cash','mada','visa','mastercard','bank','aks','gcc']
            settle_acc = cash_acc if (invoice.payment_method in settle_cash_like) else ap_acc
            db.session.add(LedgerEntry(date=invoice.date, account_id=inv_acc.id, debit=invoice.total_before_tax, credit=0, description=f'Purchase {invoice.invoice_number}'))
            db.session.add(LedgerEntry(date=invoice.date, account_id=vat_in_acc.id, debit=invoice.tax_amount, credit=0, description=f'VAT Input {invoice.invoice_number}'))
            db.session.add(LedgerEntry(date=invoice.date, account_id=settle_acc.id, credit=invoice.total_after_tax_discount, debit=0, description=f'Settlement {invoice.invoice_number}'))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logging.error('Ledger posting (purchase) failed: %s', e, exc_info=True)


        db.session.commit()

        # Emit real-time update
        socketio.emit('purchase_update', {
            'invoice_number': invoice_number,
            'supplier': form.supplier_name.data,
            'total': float(total_after_tax_discount)
        })

        flash(_('Purchase invoice created and stock updated successfully / تم إنشاء فاتورة الشراء وتحديث المخزون بنجاح'), 'success')
        return redirect(url_for('purchases'))

    # Set default date for new form
    if request.method == 'GET':
        form.date.data = datetime.now(timezone.utc).date()

    # Pagination for purchase invoices
    page = int(request.args.get('page') or 1)
    per_page = min(100, int(request.args.get('per_page') or 25))
    pag = PurchaseInvoice.query.order_by(PurchaseInvoice.date.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('purchases.html', form=form, invoices=pag.items, pagination=pag, materials_json=materials_json)

@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    form = ExpenseInvoiceForm()

    if form.validate_on_submit():
        # Generate invoice number
        last_invoice = ExpenseInvoice.query.order_by(ExpenseInvoice.id.desc()).first()
        if last_invoice and last_invoice.invoice_number and '-' in last_invoice.invoice_number:
            try:
                last_num = int(last_invoice.invoice_number.split('-')[-1])
                invoice_number = f'EXP-{datetime.now(timezone.utc).year}-{last_num + 1:03d}'
            except Exception:
                invoice_number = f'EXP-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}'
        else:
            invoice_number = f'EXP-{datetime.now(timezone.utc).year}-001'

        # Calculate totals
        total_before_tax = 0
        total_tax = 0
        total_discount = 0

        # Create invoice
        invoice = ExpenseInvoice(
            invoice_number=invoice_number,
            date=form.date.data,
            payment_method=form.payment_method.data,
            status='paid',  # Expenses are usually paid immediately
            total_before_tax=0,  # Will be calculated
            tax_amount=0,  # Will be calculated
            discount_amount=0,  # Will be calculated
            total_after_tax_discount=0,  # Will be calculated
            user_id=current_user.id
        )
        db.session.add(invoice)
        db.session.flush()

        # Add invoice items
        for item_form in form.items.entries:
            # Note: 'description' conflicts with WTForms Field.description (a string); use the nested form explicitly
            if item_form.form.description.data:  # Only process items with description
                qty = float(item_form.quantity.data)
                price = float(item_form.price_before_tax.data)
                tax = float(item_form.tax.data or 0)
                discount_pct = float(item_form.discount.data or 0)

                # Calculate amounts
                item_before_tax = price * qty
                discount = (item_before_tax + tax) * (discount_pct/100.0)
                total_item = item_before_tax + tax - discount

@app.route('/import_meals', methods=['POST'])
@login_required
def import_meals():
    try:
        if 'file' not in request.files:
            flash(_('No file selected / لم يتم اختيار ملف'), 'danger')
            return redirect(url_for('meals'))

        file = request.files['file']
        if file.filename == '':
            flash(_('No file selected / لم يتم اختيار ملف'), 'danger')
            return redirect(url_for('meals'))

        if not file.filename.lower().endswith(('.xlsx', '.xls', '.csv')):
            flash(_('Invalid file format / صيغة ملف غير صالحة'), 'danger')
            return redirect(url_for('meals'))

        # Read file using pandas
        try:
            import pandas as pd
            if file.filename.lower().endswith('.csv'):
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)
        except ImportError:
            flash(_('pandas library not installed / مكتبة pandas غير مثبتة'), 'danger')
            return redirect(url_for('meals'))
        except Exception as e:
            flash(_('Error reading file / خطأ في قراءة الملف: %(error)s', error=str(e)), 'danger')
            return redirect(url_for('meals'))

        # Expected columns: Name, Name (Arabic), Category, Cost, Selling Price
        expected_cols = ['Name', 'Name (Arabic)', 'Category', 'Cost', 'Selling Price']
        if not all(col in df.columns for col in expected_cols):
            flash(_('Invalid file format. Expected columns: %(cols)s / تنسيق ملف غير صالح. الأعمدة المطلوبة: %(cols)s',
                   cols=', '.join(expected_cols)), 'danger')
            return redirect(url_for('meals'))

        # Import meals
        imported_count = 0
        from models import Meal

        for _, row in df.iterrows():
            try:
                name = str(row['Name']).strip()
                name_ar = str(row['Name (Arabic)']).strip() if pd.notna(row['Name (Arabic)']) else ''
                category = str(row['Category']).strip() if pd.notna(row['Category']) else 'General'
                cost = float(row['Cost']) if pd.notna(row['Cost']) else 0.0
                selling_price = float(row['Selling Price']) if pd.notna(row['Selling Price']) else 0.0

                if not name:
                    continue

                # Check if meal already exists
                existing = Meal.query.filter_by(name=name).first()
                if existing:
                    continue  # Skip duplicates

                meal = Meal(
                    name=name,
                    name_ar=name_ar,
                    category=category,
                    cost=cost,
                    selling_price=selling_price,
                    profit_margin_percent=((selling_price - cost) / cost * 100) if cost > 0 else 0
                )
                db.session.add(meal)
                imported_count += 1

            except Exception as e:
                logging.warning(f'Error importing meal row: {e}')
                continue

        db.session.commit()
        flash(_('Successfully imported %(count)s meals / تم استيراد %(count)s وجبة بنجاح', count=imported_count), 'success')

    except Exception as e:
        db.session.rollback()
        logging.exception('Import meals failed')
        flash(_('Import failed / فشل الاستيراد: %(error)s', error=str(e)), 'danger')

    return redirect(url_for('meals'))
# API: Cancel draft order
@app.route('/api/draft_orders/<int:draft_id>/cancel', methods=['POST'])
@login_required
def cancel_draft_order(draft_id):
    try:
        from models import DraftOrder, Table

        draft = DraftOrder.query.get_or_404(draft_id)

        # Check permissions (user can cancel their own drafts or admin can cancel any)
        if draft.user_id != current_user.id and getattr(current_user, 'role', '') != 'admin':
            return jsonify({'success': False, 'error': 'Permission denied'}), 403

        branch_code = draft.branch_code
        table_no = draft.table_no

        # Delete the draft order (cascade will delete items)
        db.session.delete(draft)

        # Update table status if no more drafts
        remaining_drafts = DraftOrder.query.filter_by(
            branch_code=branch_code,
            table_no=table_no,
            status='draft'
        ).count()

        if remaining_drafts <= 1:  # <= 1 because we haven't committed the delete yet
            table = Table.query.filter_by(branch_code=branch_code, table_number=table_no).first()
            if table:
                table.status = 'available'
                table.updated_at = datetime.utcnow()

        db.session.commit()
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        logging.exception('Cancel draft order failed')
        return jsonify({'success': False, 'error': str(e)}), 500

# API: Add item to draft order
@app.route('/api/draft_orders/<int:draft_id>/add_item', methods=['POST'])
@login_required
def add_item_to_draft(draft_id):
    try:
        from models import DraftOrder, DraftOrderItem, Meal, Table

        draft = DraftOrder.query.get_or_404(draft_id)
        data = request.get_json() or {}

        meal_id = data.get('meal_id')
        quantity = float(data.get('quantity', 1))

        if not meal_id or quantity <= 0:
            return jsonify({'success': False, 'error': 'Invalid meal or quantity'}), 400

        meal = Meal.query.get_or_404(meal_id)

        # Calculate pricing
        settings = get_settings_safe()
        vat_rate = float(settings.vat_rate) if settings and settings.vat_rate else 15.0

        price_before_tax = float(meal.selling_price or 0)
        line_subtotal = price_before_tax * quantity
        line_tax = line_subtotal * (vat_rate / 100.0)
        total_price = line_subtotal + line_tax

        # Add item to draft
        draft_item = DraftOrderItem(
            draft_order_id=draft.id,
            meal_id=meal.id,
            product_name=meal.display_name,
            quantity=quantity,
            price_before_tax=price_before_tax,
            tax=line_tax,
            total_price=total_price
        )
        db.session.add(draft_item)

        # Update table status to reserved if this is the first item
        if len(draft.items) == 0:  # First item being added
            table = Table.query.filter_by(branch_code=draft.branch_code, table_number=draft.table_no).first()
            if not table:
                table = Table(branch_code=draft.branch_code, table_number=draft.table_no, status='reserved')
                db.session.add(table)
            else:
                table.status = 'reserved'
                table.updated_at = datetime.utcnow()

        db.session.commit()
        return jsonify({'success': True, 'item_id': draft_item.id})

    except Exception as e:
        db.session.rollback()
        logging.exception('Add item to draft failed')
        return jsonify({'success': False, 'error': str(e)}), 500
# API: Update draft order with all items
@app.route('/api/draft_orders/<int:draft_id>/update', methods=['POST'])
@login_required
def update_draft_order(draft_id):
    try:
        from models import DraftOrder, DraftOrderItem, Meal, Table

        draft = DraftOrder.query.get_or_404(draft_id)
        data = request.get_json() or {}

        # Get items from request
        items_data = data.get('items', [])
        customer_name = data.get('customer_name', '').strip()
        customer_phone = data.get('customer_phone', '').strip()
        payment_method = data.get('payment_method', 'CASH')

        # Update draft order info
        if customer_name:
            draft.customer_name = customer_name
        if customer_phone:
            draft.customer_phone = customer_phone
        draft.payment_method = payment_method

        # Clear existing items
        DraftOrderItem.query.filter_by(draft_order_id=draft.id).delete()

        # Add new items
        settings = get_settings_safe()
        vat_rate = float(settings.vat_rate) if settings and settings.vat_rate else 15.0

        for item_data in items_data:
            meal_id = item_data.get('meal_id')
            quantity = float(item_data.get('qty', 1))

            if not meal_id or quantity <= 0:
                continue

            meal = Meal.query.get(meal_id)
            if not meal:
                continue

            # Calculate pricing
            price_before_tax = float(meal.selling_price or 0)
            line_subtotal = price_before_tax * quantity
            line_tax = line_subtotal * (vat_rate / 100.0)
            total_price = line_subtotal + line_tax

            # Create draft item
            draft_item = DraftOrderItem(
                draft_order_id=draft.id,
                meal_id=meal.id,
                product_name=meal.display_name,
                quantity=quantity,
                price_before_tax=price_before_tax,
                tax=line_tax,
                total_price=total_price
            )
            db.session.add(draft_item)

        # Update table status to reserved if items exist
        if items_data:
            table = Table.query.filter_by(branch_code=draft.branch_code, table_number=draft.table_no).first()
            if not table:
                table = Table(branch_code=draft.branch_code, table_number=draft.table_no, status='reserved')
                db.session.add(table)
            else:
                table.status = 'reserved'
                table.updated_at = datetime.utcnow()

        db.session.commit()
        return jsonify({'success': True})

    except Exception as e:
        db.session.rollback()
        logging.exception('Update draft order failed')
        return jsonify({'success': False, 'error': str(e)}), 500

# Checkout draft order (convert to final invoice)
@app.route('/sales/<branch_code>/draft/<int:draft_id>/checkout', methods=['GET', 'POST'])
@login_required
def checkout_draft_order(branch_code, draft_id):
    from models import DraftOrder, SalesInvoice, SalesInvoiceItem, Payment, Table

    draft = DraftOrder.query.get_or_404(draft_id)

# API: Direct draft checkout (no additional screens)
@app.route('/api/draft/checkout', methods=['POST'])
@login_required
def api_draft_checkout():
    try:
        from models import DraftOrder, SalesInvoice, SalesInvoiceItem, Payment, Table

        data = request.get_json() or {}
        draft_id = data.get('draft_id')

        if not draft_id:
            return jsonify({'ok': False, 'error': 'Draft ID required'}), 400

        draft = DraftOrder.query.get_or_404(draft_id)

        if draft.status != 'draft':
            return jsonify({'ok': False, 'error': 'Invalid draft order'}), 400

        # Get form data
        customer_name = data.get('customer_name', '').strip()
        customer_phone = data.get('customer_phone', '').strip()
        payment_method = data.get('payment_method', 'CASH')

        # Calculate totals
        subtotal = sum(float(item.price_before_tax * item.quantity) for item in draft.items)
        tax_total = sum(float(item.tax) for item in draft.items)
        grand_total = sum(float(item.total_price) for item in draft.items)

        # Generate invoice number
        from datetime import datetime as _dt, timezone, timedelta
        saudi_tz = timezone(timedelta(hours=3))
        _now = _dt.now(saudi_tz)

        last_invoice = SalesInvoice.query.order_by(SalesInvoice.id.desc()).first()
        invoice_number = (last_invoice.id + 1) if last_invoice else 1

        # Create final invoice
        invoice = SalesInvoice(
            invoice_number=invoice_number,
            date=_now.date(),
            payment_method=payment_method,
            branch=draft.branch_code,
            table_no=draft.table_no,
            customer_name=customer_name or None,
            customer_phone=customer_phone or None,
            total_before_tax=subtotal,
            tax_amount=tax_total,
            discount_amount=0,
            total_after_tax_discount=grand_total,
            status='paid',
            user_id=current_user.id,
            created_at=_now
        )
        db.session.add(invoice)
        db.session.flush()

        # Copy items from draft to invoice
        for draft_item in draft.items:
            invoice_item = SalesInvoiceItem(
                invoice_id=invoice.id,
                meal_id=draft_item.meal_id,
                product_name=draft_item.product_name,
                quantity=draft_item.quantity,
                price_before_tax=draft_item.price_before_tax,
                tax=draft_item.tax,
                discount=draft_item.discount,
                total_price=draft_item.total_price
            )
            db.session.add(invoice_item)

        # Create payment record
        payment = Payment(
            invoice_id=invoice.id,
            invoice_type='sales',
            amount_paid=grand_total,
            payment_method=payment_method,
            payment_date=_now
        )
        db.session.add(payment)

        # Mark draft as completed
        draft.status = 'completed'

        # Update table status
        remaining_drafts = DraftOrder.query.filter_by(
            branch_code=draft.branch_code,
            table_no=draft.table_no,
            status='draft'
        ).count()

        table = Table.query.filter_by(branch_code=draft.branch_code, table_number=draft.table_no).first()
        if table:
            if remaining_drafts <= 1:  # This draft will be completed
                table.status = 'available'
            else:
                table.status = 'reserved'  # Still has other drafts
            table.updated_at = _now

        db.session.commit()

        # Return success with print URL
        print_url = url_for('sales_receipt', invoice_id=invoice.id)
        return jsonify({
            'ok': True,
            'status': 'success',
            'invoice_id': invoice.id,
            'print_url': print_url
        })

    except Exception as e:
        db.session.rollback()
        logging.exception('API draft checkout failed')
        return jsonify({'ok': False, 'error': str(e)}), 500
@app.route('/admin/fix_database', methods=['GET'])
@login_required
def fix_database_route():
    """Comprehensive database fix route"""
    if not hasattr(current_user, 'role') or current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403

    try:
        from sqlalchemy import text

        results = []

        # 1. Add table_no column to sales_invoices if missing
        try:
            with db.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'sales_invoices'
                    AND column_name = 'table_no'
                """))

                if not result.fetchone():
                    conn.execute(text("ALTER TABLE sales_invoices ADD COLUMN table_no INTEGER"))
                    conn.commit()
                    results.append("✅ Added table_no column to sales_invoices")
                else:
                    results.append("✅ table_no column already exists")
        except Exception as e:
            results.append(f"⚠️ Error with table_no: {e}")

        # 2. Create tables table if missing
        try:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS tables (
                        id SERIAL PRIMARY KEY,
                        branch_code VARCHAR(20) NOT NULL,
                        table_number INTEGER NOT NULL,
                        status VARCHAR(20) DEFAULT 'available',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(branch_code, table_number)
                    )
                """))
                conn.commit()
            results.append("✅ tables table created/verified")
        except Exception as e:
            results.append(f"⚠️ Error with tables table: {e}")

        # 3. Create draft_orders table if missing
        try:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS draft_orders (
                        id SERIAL PRIMARY KEY,
                        branch_code VARCHAR(20) NOT NULL,
                        table_no INTEGER NOT NULL,
                        customer_name VARCHAR(100),
                        customer_phone VARCHAR(30),
                        payment_method VARCHAR(20) DEFAULT 'CASH',
                        status VARCHAR(20) DEFAULT 'draft',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        user_id INTEGER NOT NULL
                    )
                """))
                conn.commit()
            results.append("✅ draft_orders table created/verified")
        except Exception as e:
            results.append(f"⚠️ Error with draft_orders table: {e}")

        # 4. Create draft_order_items table if missing
        try:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS draft_order_items (
                        id SERIAL PRIMARY KEY,
                        draft_order_id INTEGER NOT NULL,
                        meal_id INTEGER,
                        product_name VARCHAR(200) NOT NULL,
                        quantity NUMERIC(10,2) NOT NULL,
                        price_before_tax NUMERIC(12,2) NOT NULL,
                        tax NUMERIC(12,2) NOT NULL DEFAULT 0,
                        discount NUMERIC(12,2) NOT NULL DEFAULT 0,
                        total_price NUMERIC(12,2) NOT NULL
                    )
                """))
                conn.commit()
            results.append("✅ draft_order_items table created/verified")
        except Exception as e:
            results.append(f"⚠️ Error with draft_order_items table: {e}")

        # 5. Add foreign key constraints if they don't exist
        try:
            with db.engine.connect() as conn:
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.table_constraints
                            WHERE constraint_name = 'draft_order_items_draft_order_id_fkey'
                        ) THEN
                            ALTER TABLE draft_order_items
                            ADD CONSTRAINT draft_order_items_draft_order_id_fkey
                            FOREIGN KEY (draft_order_id) REFERENCES draft_orders(id) ON DELETE CASCADE;
                        END IF;
                    END $$;
                """))
                conn.commit()
            results.append("✅ Foreign key constraints added/verified")
        except Exception as e:
            results.append(f"⚠️ Error with foreign keys: {e}")

        return jsonify({
            'ok': True,
            'status': 'Database fix completed successfully',
            'results': results
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/invoices')
@login_required
def invoices():
    try:
        from sqlalchemy import func, text
        # Normalize type
        raw_type = (request.args.get('type') or 'all').lower()
        if raw_type in ['purchases','purchase']: tfilter = 'purchase'
        elif raw_type in ['expenses','expense']: tfilter = 'expense'
        elif raw_type in ['sales','sale']: tfilter = 'sales'
        else: tfilter = 'all'

        # Simple approach - get invoices directly without complex queries
        rows = []

        # Sales invoices
        if tfilter in ['all', 'sales']:
            try:
                sales_invoices = SalesInvoice.query.order_by(SalesInvoice.date.desc()).all()
                for inv in sales_invoices:
                    rows.append({
                        'id': inv.id,
                        'invoice_number': inv.invoice_number,
                        'invoice_type': 'sales',
                        'customer_supplier': inv.customer_name or 'Customer',
                        'total_amount': float(inv.total_after_tax_discount or 0),
                        'paid_amount': 0,  # Will be calculated from payments
                        'remaining_amount': float(inv.total_after_tax_discount or 0),
                        'status': inv.status or 'unpaid',
                        'due_date': inv.date
                    })
            except Exception as e:
                logging.warning(f'Error loading sales invoices: {e}')

        # Purchase invoices
        if tfilter in ['all', 'purchase']:
            try:
                purchase_invoices = PurchaseInvoice.query.order_by(PurchaseInvoice.date.desc()).all()
                for inv in purchase_invoices:
                    rows.append({
                        'id': inv.id,
                        'invoice_number': getattr(inv, 'invoice_number', inv.id),
                        'invoice_type': 'purchase',
                        'customer_supplier': getattr(inv, 'supplier_name', 'Supplier'),
                        'total_amount': float(getattr(inv, 'total_after_tax_discount', 0) or 0),
                        'paid_amount': 0,
                        'remaining_amount': float(getattr(inv, 'total_after_tax_discount', 0) or 0),
                        'status': getattr(inv, 'status', 'unpaid'),
                        'due_date': inv.date
                    })
            except Exception as e:
                logging.warning(f'Error loading purchase invoices: {e}')

        # Expense invoices
        if tfilter in ['all', 'expense']:
            try:
                expense_invoices = ExpenseInvoice.query.order_by(ExpenseInvoice.date.desc()).all()
                for inv in expense_invoices:
                    rows.append({
                        'id': inv.id,
                        'invoice_number': getattr(inv, 'invoice_number', inv.id),
                        'invoice_type': 'expense',
                        'customer_supplier': 'Expense',
                        'total_amount': float(getattr(inv, 'total_after_tax_discount', 0) or 0),
                        'paid_amount': 0,
                        'remaining_amount': float(getattr(inv, 'total_after_tax_discount', 0) or 0),
                        'status': getattr(inv, 'status', 'unpaid'),
                        'due_date': inv.date
                    })
            except Exception as e:
                logging.warning(f'Error loading expense invoices: {e}')

        # Sort by date descending
        rows.sort(key=lambda x: x['due_date'] if x['due_date'] else datetime.min.date(), reverse=True)

        current_type = tfilter
        return render_template('invoices.html', invoices=rows, current_type=current_type)

    except Exception as e:
        logging.exception('Error in invoices route')
        flash(_('Error loading invoices / خطأ في تحميل الفواتير'), 'danger')
        return redirect(url_for('dashboard'))

    rows = []
    def paid_map_for(kind, ids):
        if not ids: return {}
        mm = db.session.query(Payment.invoice_id, func.coalesce(func.sum(Payment.amount_paid), 0)).\
            filter(Payment.invoice_type==kind, Payment.invoice_id.in_(ids)).\
            group_by(Payment.invoice_id).all()
        return {pid: float(total or 0) for (pid,total) in mm}

    if tfilter in ['all','sales']:
        sales = sales_q.order_by(SalesInvoice.date.desc()).all()
        paid = paid_map_for('sales', [s.id for s in sales])
        for s in sales:
            total = float(s.total_after_tax_discount or 0)
            p = paid.get(s.id, 0.0)
            rows.append({
                'id': s.id,
                'invoice_number': s.invoice_number,
                'invoice_type': 'sales',
                'customer_supplier': s.customer_name or '-',
                'total_amount': total,
                'paid_amount': p,
                'remaining_amount': max(total - p, 0.0),
                'status': s.status,
                'due_date': None,
            })
    if tfilter in ['all','purchase']:
        purchases = purchase_q.order_by(PurchaseInvoice.date.desc()).all()
        paid = paid_map_for('purchase', [p.id for p in purchases])
        for pch in purchases:
            total = float(pch.total_after_tax_discount or 0)
            p = paid.get(pch.id, 0.0)
            rows.append({
                'id': pch.id,
                'invoice_number': pch.invoice_number,
                'invoice_type': 'purchase',
                'customer_supplier': pch.supplier_name or '-',
                'total_amount': total,
                'paid_amount': p,
                'remaining_amount': max(total - p, 0.0),
                'status': pch.status,
                'due_date': None,
            })
    if tfilter in ['all','expense']:
        expenses = expense_q.order_by(ExpenseInvoice.date.desc()).all()
        paid = paid_map_for('expense', [e.id for e in expenses])
        for ex in expenses:
            total = float(ex.total_after_tax_discount or 0)
            p = paid.get(ex.id, 0.0)
            rows.append({
                'id': ex.id,
                'invoice_number': ex.invoice_number,
                'invoice_type': 'expense',
                'customer_supplier': 'Expense',
                'total_amount': total,
                'paid_amount': p,
                'remaining_amount': max(total - p, 0.0),
                'status': ex.status,
                'due_date': None,
            })

    # Sort unified rows by invoice number or leave as-is; here sort by id desc
    rows.sort(key=lambda r: (r.get('id') or 0), reverse=True)

    # For nav highlighting, keep original choice
    current_type = raw_type
    return render_template('invoices.html', invoices=rows, current_type=current_type)


@app.route('/invoices/delete', methods=['POST'])
@login_required
def invoices_delete():
    # Admin-only for safety; can be relaxed later per-type permissions
    if getattr(current_user, 'role', '') != 'admin':
        flash(_('You do not have permission / لا تملك صلاحية الوصول'), 'danger')
        return redirect(url_for('invoices', type=request.args.get('type') or 'all'))
    from models import SalesInvoice, SalesInvoiceItem, PurchaseInvoice, PurchaseInvoiceItem, ExpenseInvoice, ExpenseInvoiceItem, Payment
    scope = (request.form.get('scope') or '').lower()
    inv_type = (request.form.get('invoice_type') or '').lower()
    ids = request.form.getlist('invoice_ids') or []
    deleted = 0
    try:
        def delete_sales(ids_list):
            nonlocal deleted
            if ids_list:
                SalesInvoiceItem.query.filter(SalesInvoiceItem.invoice_id.in_(ids_list)).delete(synchronize_session=False)
                Payment.query.filter(Payment.invoice_type=='sales', Payment.invoice_id.in_(ids_list)).delete(synchronize_session=False)
                deleted += SalesInvoice.query.filter(SalesInvoice.id.in_(ids_list)).delete(synchronize_session=False)
            else:
                # Delete all sales
                SalesInvoiceItem.query.delete(synchronize_session=False)
                Payment.query.filter_by(invoice_type='sales').delete(synchronize_session=False)
                deleted += SalesInvoice.query.delete(synchronize_session=False)
        def delete_purchase(ids_list):
            nonlocal deleted
            if ids_list:
                PurchaseInvoiceItem.query.filter(PurchaseInvoiceItem.invoice_id.in_(ids_list)).delete(synchronize_session=False)
                Payment.query.filter(Payment.invoice_type=='purchase', Payment.invoice_id.in_(ids_list)).delete(synchronize_session=False)
                deleted += PurchaseInvoice.query.filter(PurchaseInvoice.id.in_(ids_list)).delete(synchronize_session=False)
            else:
                PurchaseInvoiceItem.query.delete(synchronize_session=False)
                Payment.query.filter_by(invoice_type='purchase').delete(synchronize_session=False)
                deleted += PurchaseInvoice.query.delete(synchronize_session=False)
        def delete_expense(ids_list):
            nonlocal deleted
            if ids_list:
                ExpenseInvoiceItem.query.filter(ExpenseInvoiceItem.invoice_id.in_(ids_list)).delete(synchronize_session=False)
                Payment.query.filter(Payment.invoice_type=='expense', Payment.invoice_id.in_(ids_list)).delete(synchronize_session=False)
                deleted += ExpenseInvoice.query.filter(ExpenseInvoice.id.in_(ids_list)).delete(synchronize_session=False)
            else:
                ExpenseInvoiceItem.query.delete(synchronize_session=False)
                Payment.query.filter_by(invoice_type='expense').delete(synchronize_session=False)
                deleted += ExpenseInvoice.query.delete(synchronize_session=False)

        if scope == 'selected':
            # Expect mixed types? Our table is unified but ids alone don't carry type. Prevent mixed delete for now.
            # Require invoice_type parameter when deleting selected; otherwise assume current tab type
            if not inv_type:
                inv_type = (request.args.get('type') or request.form.get('current_type') or 'all').lower()
            if inv_type == 'sales':
                delete_sales([int(x) for x in ids])
            elif inv_type in ['purchases','purchase']:
                delete_purchase([int(x) for x in ids])
            elif inv_type in ['expenses','expense']:
                delete_expense([int(x) for x in ids])
            else:
                flash(_('Please select a specific type tab before deleting / اختر نوع الفواتير قبل الحذف'), 'warning')
                return redirect(url_for('invoices', type='all'))
        elif scope == 'type':
            if inv_type == 'sales':
                delete_sales([])
            elif inv_type in ['purchases','purchase']:
                delete_purchase([])
            elif inv_type in ['expenses','expense']:
                delete_expense([])
            else:
                flash(_('Unknown invoice type / نوع فواتير غير معروف'), 'danger')
                return redirect(url_for('invoices', type='all'))
        else:
            flash(_('Invalid request / طلب غير صالح'), 'danger')
            return redirect(url_for('invoices', type='all'))
        db.session.commit()
        flash(_('Deleted %(n)s invoices / تم حذف %(n)s فاتورة', n=deleted), 'success')
    except Exception:
        db.session.rollback()
        logging.exception('invoices_delete failed')
        flash(_('Delete failed / فشل الحذف'), 'danger')
    # Redirect back preserving current tab
    ret_type = inv_type if inv_type in ['sales','purchases','expenses'] else (request.args.get('type') or 'all')
    return redirect(url_for('invoices', type=ret_type))


@app.route('/invoices/<string:kind>/<int:invoice_id>')
@login_required
def view_invoice(kind, invoice_id):
    kind = (kind or '').lower()
    inv = None
    items = []
    title = 'Invoice'
    if kind == 'sales':
        inv = SalesInvoice.query.get_or_404(invoice_id)
        if not can_perm('sales','view', branch_scope=inv.branch):
            flash(_('You do not have permission / لا تملك صلاحية الوصول'), 'danger')
            return redirect(url_for('invoices'))
        items = SalesInvoiceItem.query.filter_by(invoice_id=inv.id).all()
        title = 'Sales Invoice'
    elif kind == 'purchase':
        inv = PurchaseInvoice.query.get_or_404(invoice_id)
        items = PurchaseInvoiceItem.query.filter_by(invoice_id=inv.id).all()
        title = 'Purchase Invoice'
    elif kind == 'expense':
        inv = ExpenseInvoice.query.get_or_404(invoice_id)
        items = ExpenseInvoiceItem.query.filter_by(invoice_id=inv.id).all()
        title = 'Expense Invoice'
    else:
        flash(_('Unknown invoice type / نوع فاتورة غير معروف'), 'danger')
        return redirect(url_for('invoices'))

    # Compute paid/remaining from payments
    from sqlalchemy import func
    paid = float(db.session.query(func.coalesce(func.sum(Payment.amount_paid), 0)).\
        filter_by(invoice_type=kind, invoice_id=invoice_id).scalar() or 0)
    total = float(getattr(inv, 'total_after_tax_discount', 0) or 0)
    remaining = max(total - paid, 0.0)

    return render_template('invoice_view.html', kind=kind, inv=inv, items=items, title=title, paid=paid, remaining=remaining)

@app.route('/inventory')
@login_required
def inventory():
    # Get all raw materials and meals for display
    raw_materials = RawMaterial.query.filter_by(active=True).all()
    meals = Meal.query.filter_by(active=True).all()
    return render_template('inventory.html', raw_materials=raw_materials, meals=meals)



@app.route('/employees', methods=['GET', 'POST'])
@login_required
def employees():
    form = EmployeeForm()
    if form.validate_on_submit():
        try:
            emp = Employee(
                employee_code=form.employee_code.data.strip(),
                full_name=form.full_name.data.strip(),
                national_id=form.national_id.data.strip(),
                department=form.department.data.strip() if form.department.data else None,
                position=form.position.data.strip() if form.position.data else None,
                phone=form.phone.data.strip() if form.phone.data else None,
                email=form.email.data.strip() if form.email.data else None,
                hire_date=form.hire_date.data,
                status=form.status.data
            )
            db.session.add(emp)
            db.session.commit()
            flash(_('تم إضافة الموظف بنجاح / Employee added successfully'), 'success')
            return redirect(url_for('employees'))
        except Exception as e:
            db.session.rollback()
            flash(_('تعذرت إضافة الموظف. تحقق من أن رقم الموظف والهوية غير مكررين. / Could not add employee. Ensure code and national id are unique.'), 'danger')
    employees_list = Employee.query.order_by(Employee.full_name.asc()).all()
    return render_template('employees.html', form=form, employees=employees_list)


@app.route('/salaries', methods=['GET', 'POST'])
@login_required
def salaries():
    # Redirect to monthly view as primary workflow
    if request.method == 'GET' and not request.args:
        return redirect(url_for('salaries_monthly'))
    form = SalaryForm()
    # Load employees into choices
    form.employee_id.choices = [(e.id, e.full_name) for e in Employee.query.order_by(Employee.full_name.asc()).all()]

    if form.validate_on_submit():
        try:
            basic = float(form.basic_salary.data or 0)
            allowances = float(form.allowances.data or 0)
            deductions = float(form.deductions.data or 0)
            prev_due = float(form.previous_salary_due.data or 0)
            total = basic + allowances - deductions + prev_due

            salary = Salary(
                employee_id=form.employee_id.data,
                year=form.year.data,
                month=form.month.data,
                basic_salary=basic,
                allowances=allowances,
                deductions=deductions,
                previous_salary_due=prev_due,
                total_salary=total,
                status=form.status.data
            )
            db.session.add(salary)
            db.session.commit()
            flash(_('تم حفظ الراتب بنجاح / Salary saved successfully'), 'success')
            return redirect(url_for('salaries'))
        except Exception:
            db.session.rollback()
            flash(_('تعذر حفظ الراتب. تأكد من عدم تكرار نفس الشهر لنفس الموظف / Could not save. Ensure month is unique per employee'), 'danger')

    salaries_list = Salary.query.order_by(Salary.year.desc(), Salary.month.desc()).all()
    return render_template('salaries.html', form=form, salaries=salaries_list)

@app.route('/payments', methods=['GET'])
@login_required
def payments():
    status_filter = request.args.get('status')
    type_filter = request.args.get('type')

    # Simple approach - get invoices directly from models
    try:
        # Sales invoices
        sales_invoices = []
        try:
            sales_list = SalesInvoice.query.order_by(SalesInvoice.date.desc()).all()
            for inv in sales_list:
                sales_invoices.append({
                    'id': inv.id,
                    'type': 'sales',
                    'party': inv.customer_name or 'Customer',
                    'total': float(inv.total_after_tax_discount or 0),
                    'paid': 0,  # Will be calculated from payments
                    'date': inv.date,
                    'status': inv.status or 'unpaid'
                })
        except Exception as e:
            logging.warning(f'Error loading sales invoices: {e}')

        # Purchase invoices
        purchase_invoices = []
        try:
            purchase_list = PurchaseInvoice.query.order_by(PurchaseInvoice.date.desc()).all()
            for inv in purchase_list:
                purchase_invoices.append({
                    'id': inv.id,
                    'type': 'purchase',
                    'party': getattr(inv, 'supplier_name', 'Supplier'),
                    'total': float(getattr(inv, 'total_after_tax_discount', 0) or 0),
                    'paid': 0,
                    'date': inv.date,
                    'status': getattr(inv, 'status', 'unpaid')
                })
        except Exception as e:
            logging.warning(f'Error loading purchase invoices: {e}')

        # Expense invoices
        expense_invoices = []
        try:
            expense_list = ExpenseInvoice.query.order_by(ExpenseInvoice.date.desc()).all()
            for inv in expense_list:
                expense_invoices.append({
                    'id': inv.id,
                    'type': 'expense',
                    'party': 'Expense',
                    'total': float(getattr(inv, 'total_after_tax_discount', 0) or 0),
                    'paid': 0,
                    'date': inv.date,
                    'status': getattr(inv, 'status', 'unpaid')
                })
        except Exception as e:
            logging.warning(f'Error loading expense invoices: {e}')

        # Apply filters if needed
        if status_filter:
            all_invoices = [inv for inv in all_invoices if inv.get('status') == status_filter]

        if type_filter and type_filter != 'all':
            all_invoices = [inv for inv in all_invoices if inv.get('type') == type_filter]

        return render_template('payments.html', invoices=all_invoices, status_filter=status_filter, type_filter=type_filter)

    except Exception as e:
        logging.exception('Error in payments route')
        flash(_('Error loading payments / خطأ في تحميل المدفوعات'), 'danger')
        return redirect(url_for('dashboard'))

@app.route('/reports', methods=['GET'])
@login_required
def reports():
    try:
        from sqlalchemy import func, cast, Date, text
        period = request.args.get('period', 'this_month')
        start_arg = request.args.get('start_date')
        end_arg = request.args.get('end_date')

        today = datetime.now(timezone.utc).date()

        if period == 'today':
            start_dt = end_dt = today
        elif period == 'this_week':
            start_dt = today - datetime.timedelta(days=today.weekday())
            end_dt = today
        elif period == 'this_month':
            start_dt = today.replace(day=1)
            end_dt = today
        elif period == 'this_year':
            start_dt = today.replace(month=1, day=1)
            end_dt = today
        elif period == 'custom' and start_arg and end_arg:
            try:
                start_dt = datetime.strptime(start_arg, '%Y-%m-%d').date()
                end_dt = datetime.strptime(end_arg, '%Y-%m-%d').date()
            except Exception:
                start_dt = today.replace(day=1)
                end_dt = today
        else:
            start_dt = today.replace(day=1)
            end_dt = today

        # Optional branch filter
        branch_filter = request.args.get('branch')
        if branch_filter and branch_filter != 'all':
            sales_place = db.session.query(func.coalesce(func.sum(SalesInvoice.total_after_tax_discount), 0)) \
                .filter(SalesInvoice.date.between(start_dt, end_dt), SalesInvoice.branch == branch_filter).scalar() or 0
            sales_china = 0
            total_sales = float(sales_place)
        else:
            # Sales totals by branch
            sales_place = db.session.query(func.coalesce(func.sum(SalesInvoice.total_after_tax_discount), 0)) \
                .filter(SalesInvoice.date.between(start_dt, end_dt), SalesInvoice.branch == 'place_india').scalar() or 0
            sales_china = db.session.query(func.coalesce(func.sum(SalesInvoice.total_after_tax_discount), 0)) \
                .filter(SalesInvoice.date.between(start_dt, end_dt), SalesInvoice.branch == 'china_town').scalar() or 0
            total_sales = float(sales_place) + float(sales_china)

    # Purchases and Expenses
    total_purchases = float(db.session.query(func.coalesce(func.sum(PurchaseInvoice.total_after_tax_discount), 0))
        .filter(PurchaseInvoice.date.between(start_dt, end_dt)).scalar() or 0)
    total_expenses = float(db.session.query(func.coalesce(func.sum(ExpenseInvoice.total_after_tax_discount), 0))
        .filter(ExpenseInvoice.date.between(start_dt, end_dt)).scalar() or 0)

    # Salaries within period: compute by month-year mapping to 1st day of month
    salaries_rows = Salary.query.all()
    total_salaries = 0.0
    for s in salaries_rows:
        try:
            s_date = datetime(s.year, s.month, 1).date()
            if start_dt <= s_date <= end_dt:
                total_salaries += float(s.total_salary or 0)
        except Exception:
            continue

    profit = float(total_sales) - (float(total_purchases) + float(total_expenses) + float(total_salaries))

    # Line chart: daily sales
    daily_rows = db.session.query(SalesInvoice.date.label('d'), func.coalesce(func.sum(SalesInvoice.total_after_tax_discount), 0).label('t')) \
        .filter(SalesInvoice.date.between(start_dt, end_dt)) \
        .group_by(SalesInvoice.date) \
        .order_by(SalesInvoice.date.asc()).all()
    line_labels = [r.d.strftime('%Y-%m-%d') for r in daily_rows]
    line_values = [float(r.t or 0) for r in daily_rows]

    # Payment method distribution across invoices
    def pm_counts(model, date_col, method_col):
        rows = db.session.query(getattr(model, method_col), func.count('*')) \
            .filter(getattr(model, date_col).between(start_dt, end_dt)) \
            .group_by(getattr(model, method_col)).all()
        return { (k or 'unknown'): int(v) for k, v in rows }

    pm_map = {}
    for d in (pm_counts(SalesInvoice, 'date', 'payment_method'),
              pm_counts(PurchaseInvoice, 'date', 'payment_method'),
              pm_counts(ExpenseInvoice, 'date', 'payment_method')):
        for k, v in d.items():
            pm_map[k] = pm_map.get(k, 0) + v
    pm_labels = list(pm_map.keys())
    pm_values = [pm_map[k] for k in pm_labels]

    # Comparison bars: totals
    comp_labels = ['Sales', 'Purchases', 'Expenses+Salaries']
    comp_values = [float(total_sales), float(total_purchases), float(total_expenses) + float(total_salaries)]

    # Cash flows from Payments table
    start_dt_dt = datetime.combine(start_dt, datetime.min.time())
    end_dt_dt = datetime.combine(end_dt, datetime.max.time())
    inflow = float(db.session.query(func.coalesce(func.sum(Payment.amount_paid), 0)).filter(
        Payment.invoice_type == 'sales', Payment.payment_date.between(start_dt_dt, end_dt_dt)
    ).scalar() or 0)
    outflow = float(db.session.query(func.coalesce(func.sum(Payment.amount_paid), 0)).filter(
        Payment.invoice_type.in_(['purchase','expense','salary']), Payment.payment_date.between(start_dt_dt, end_dt_dt)
    ).scalar() or 0)
    net_cash = inflow - outflow

    # Top products by quantity
    top_rows = db.session.query(SalesInvoiceItem.product_name, func.coalesce(func.sum(SalesInvoiceItem.quantity), 0)) \
        .join(SalesInvoice, SalesInvoiceItem.invoice_id == SalesInvoice.id) \
        .filter(SalesInvoice.date.between(start_dt, end_dt)) \
        .group_by(SalesInvoiceItem.product_name) \
        .order_by(func.sum(SalesInvoiceItem.quantity).desc()) \
        .limit(10).all()
        top_labels = [r[0] for r in top_rows]

        # Settings for labels/currency
        s = get_settings_safe()
        place_lbl = s.place_india_label if s and s.place_india_label else 'Place India'
        china_lbl = s.china_town_label if s and s.china_town_label else 'China Town'
        currency = s.currency if s and s.currency else 'SAR'

        # Simple fallback data for now
        return render_template('reports.html',
            period=period, start_date=today, end_date=today,
            sales_place=0, sales_china=0, total_sales=0,
            total_purchases=0, total_expenses=0, total_salaries=0, profit=0,
            line_labels=[], line_values=[],
            pm_labels=[], pm_values=[],
            comp_labels=[], comp_values=[],
            inflow=0, outflow=0, net_cash=0,
            top_labels=[], top_values=[],
            low_stock=[],
            place_lbl='Place India', china_lbl='China Town', currency='SAR'
        )
    except Exception as e:
        logging.exception('Error in reports route')
        flash(_('Error loading reports / خطأ في تحميل التقارير'), 'danger')
        return redirect(url_for('dashboard'))



@app.route('/register_payment', methods=['POST'])
@login_required
def register_payment_ajax():
    from sqlalchemy import literal
    invoice_id = int(request.form['invoice_id'])
    invoice_type = request.form['invoice_type']
    amt_str = request.form.get('amount', '').strip().replace(',', '.')
    try:
        amount = float(amt_str)
    except Exception:
        return jsonify({'status':'error', 'message':'invalid_amount'}), 400
    if amount <= 0:
        return jsonify({'status':'error', 'message':'invalid_amount'}), 400
    method = (request.form.get('payment_method') or 'CASH').strip().upper()

    # Register payment
    pay = Payment(invoice_id=invoice_id, invoice_type=invoice_type, amount_paid=amount, payment_method=method)
    db.session.add(pay)

    # Update invoice paid and status according to invoice type
    remaining = None
    if invoice_type == 'sales':
        inv = SalesInvoice.query.get(invoice_id)
        if not inv: return jsonify({'status':'error'}), 404
        paid = float(getattr(inv, 'paid_amount', 0) or 0) + amount
        inv.paid_amount = paid
        total = float(inv.total_after_tax_discount)
        inv.status = 'paid' if paid >= total else ('partial' if paid > 0 else 'unpaid')
    elif invoice_type == 'purchase':
        inv = PurchaseInvoice.query.get(invoice_id)
        if not inv: return jsonify({'status':'error'}), 404
        paid = float(getattr(inv, 'paid_amount', 0) or 0) + amount
        inv.paid_amount = paid
        total = float(inv.total_after_tax_discount)
        inv.status = 'paid' if paid >= total else ('partial' if paid > 0 else 'unpaid')
    elif invoice_type == 'expense':
        inv = ExpenseInvoice.query.get(invoice_id)
        if not inv: return jsonify({'status':'error'}), 404
        paid = float(getattr(inv, 'paid_amount', 0) or 0) + amount
        inv.paid_amount = paid
        total = float(inv.total_after_tax_discount)
        inv.status = 'paid' if paid >= total else ('partial' if paid > 0 else 'paid')  # expenses usually paid
    elif invoice_type == 'salary':
        inv = Salary.query.get(invoice_id)
        if not inv: return jsonify({'status':'error'}), 404
        paid = float(getattr(inv, 'paid_amount', 0) or 0) + amount
        inv.paid_amount = paid
        total = float(inv.total_salary)
        inv.status = 'paid' if paid >= total else ('partial' if paid > 0 else 'unpaid')
    else:
        return jsonify({'status':'error'}), 400
    # Ledger postings for payments: adjust AR/AP/Cash
    try:
        def get_or_create(code, name, type_):
            acc = Account.query.filter_by(code=code).first()
            if not acc:
                acc = Account(code=code, name=name, type=type_)
                db.session.add(acc); db.session.flush()
            return acc
        cash_acc = get_or_create('1000', 'Cash', 'ASSET')
        ar_acc = get_or_create('1100', 'Accounts Receivable', 'ASSET')
        ap_acc = get_or_create('2000', 'Accounts Payable', 'LIABILITY')

        if invoice_type == 'sales':
            # receipt: debit cash, credit AR
            db.session.add(LedgerEntry(date=pay.payment_date.date(), account_id=cash_acc.id, debit=amount, credit=0, description=f'Receipt sales #{invoice_id}'))
            db.session.add(LedgerEntry(date=pay.payment_date.date(), account_id=ar_acc.id, debit=0, credit=amount, description=f'Settle AR sales #{invoice_id}'))
        elif invoice_type in ['purchase','expense','salary']:
            # payment: credit cash, debit AP (or expense/salary direct, but we keep AP)
            db.session.add(LedgerEntry(date=pay.payment_date.date(), account_id=ap_acc.id, debit=amount, credit=0, description=f'Settle AP {invoice_type} #{invoice_id}'))
            db.session.add(LedgerEntry(date=pay.payment_date.date(), account_id=cash_acc.id, debit=0, credit=amount, description=f'Payment {invoice_type} #{invoice_id}'))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.error('Ledger posting (payment) failed: %s', e, exc_info=True)


    db.session.commit()

    # Emit socket event (if desired)
    try:
        socketio.emit('payment_update', {'invoice_id': invoice_id, 'invoice_type': invoice_type, 'amount': amount})
    except Exception:
        pass

    return jsonify({'status': 'success'})






# Employees: Edit

# Deprecated inline VAT route is replaced by blueprint

@app.route('/employees/<int:emp_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    form = EmployeeForm(obj=emp)
    if form.validate_on_submit():
        try:
            emp.employee_code = form.employee_code.data.strip()
            emp.full_name = form.full_name.data.strip()
            emp.national_id = form.national_id.data.strip()
            emp.department = form.department.data.strip() if form.department.data else None
            emp.position = form.position.data.strip() if form.position.data else None
            emp.phone = form.phone.data.strip() if form.phone.data else None
            emp.email = form.email.data.strip() if form.email.data else None
            emp.hire_date = form.hire_date.data
            emp.status = form.status.data
            db.session.commit()
            flash(_('تم تعديل بيانات الموظف / Employee updated'), 'success')
            return redirect(url_for('employees'))
        except Exception:
            db.session.rollback()
            flash(_('تعذر التعديل. تحقق من عدم تكرار الرمز/الهوية / Could not update. Ensure code/national id are unique.'), 'danger')
    return render_template('employees.html', form=form, employees=None)

# Employees: Delete
@app.route('/employees/<int:emp_id>/delete', methods=['POST'])
@login_required
def delete_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    try:
        if emp.salaries and len(emp.salaries) > 0:
            flash(_('لا يمكن حذف الموظف لوجود رواتب مرتبطة / Cannot delete employee with linked salaries'), 'danger')
            return redirect(url_for('employees'))
        db.session.delete(emp)
        db.session.commit()
        flash(_('تم حذف الموظف / Employee deleted'), 'info')
    except Exception:
        db.session.rollback()
        flash(_('تعذر حذف الموظف / Could not delete employee'), 'danger')
    return redirect(url_for('employees'))

# Salaries: Edit
@app.route('/salaries/<int:salary_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_salary(salary_id):
    sal = Salary.query.get_or_404(salary_id)
    form = SalaryForm(obj=sal)
    form.employee_id.choices = [(e.id, e.full_name) for e in Employee.query.order_by(Employee.full_name.asc()).all()]
    if request.method == 'GET':
        form.employee_id.data = sal.employee_id
        form.month.data = sal.month
    if form.validate_on_submit():
        try:
            sal.employee_id = form.employee_id.data
            sal.year = form.year.data
            sal.month = form.month.data
            sal.basic_salary = float(form.basic_salary.data or 0)
            sal.allowances = float(form.allowances.data or 0)
            sal.deductions = float(form.deductions.data or 0)
            sal.previous_salary_due = float(form.previous_salary_due.data or 0)
            sal.total_salary = sal.basic_salary + sal.allowances - sal.deductions + sal.previous_salary_due
            sal.status = form.status.data
            db.session.commit()
            flash(_('تم تعديل الراتب / Salary updated'), 'success')
            return redirect(url_for('salaries'))
        except Exception:
            db.session.rollback()
            flash(_('تعذر تعديل الراتب. تحقق من عدم تكرار الشهر لنفس الموظف / Could not update. Ensure month is unique per employee'), 'danger')
    return render_template('salaries.html', form=form, salaries=None)

# Salaries: Delete
# Payroll statements (كشف الرواتب)
@app.route('/salaries/statements', methods=['GET'])
@login_required
def salaries_statements():
    # Permission: view
    try:
        if not (getattr(current_user,'role','')=='admin' or can_perm('salaries','view')):
            flash(_('You do not have permission / لا تملك صلاحية الوصول'), 'danger')
            return redirect(url_for('dashboard'))
    except Exception:
        pass
    # Year/month
    try:
        year = int(request.args.get('year') or datetime.now(timezone.utc).year)
    except Exception:
        year = datetime.now(timezone.utc).year
    try:
        month = int(request.args.get('month') or datetime.now(timezone.utc).month)
    except Exception:
        month = datetime.now(timezone.utc).month

    from sqlalchemy import func
    qs = Salary.query.filter_by(year=year, month=month).join(Employee).order_by(Employee.full_name.asc())
    recs = qs.all()
    # Payments per salary
    pays = db.session.query(Payment.invoice_id, func.coalesce(func.sum(Payment.amount_paid), 0)).\
        filter(Payment.invoice_type=='salary', Payment.invoice_id.in_([r.id for r in recs])).\
        group_by(Payment.invoice_id).all()
    paid_map = {pid: float(total or 0) for (pid,total) in pays}

    rows = []
    totals = dict(basic=0.0, allow=0.0, ded=0.0, prev=0.0, total=0.0, paid=0.0, remaining=0.0)
    for s in recs:
        paid = paid_map.get(s.id, 0.0)
        total = float(s.total_salary or 0)
        remaining = max(total - paid, 0.0)
        rows.append({
            'id': s.id,
            'employee_name': s.employee.full_name if s.employee else str(s.employee_id),
            'basic': float(s.basic_salary or 0),
            'allow': float(s.allowances or 0),
            'ded': float(s.deductions or 0),
            'prev': float(s.previous_salary_due or 0),
            'total': total,
            'paid': paid,
            'remaining': remaining,
            'status': s.status,
        })
        totals['basic'] += float(s.basic_salary or 0)
        totals['allow'] += float(s.allowances or 0)
        totals['ded'] += float(s.deductions or 0)
        totals['prev'] += float(s.previous_salary_due or 0)
        totals['total'] += total
        totals['paid'] += paid
        totals['remaining'] += remaining

    return render_template('salaries_statements.html', year=year, month=month, rows=rows, totals=totals)

@app.route('/salaries/statements/print', methods=['GET'])
@login_required
def salaries_statements_print():
    # Permission: print
    try:
        if not (getattr(current_user,'role','')=='admin' or can_perm('salaries','print')):
            flash(_('You do not have permission / لا تملك صلاحية الوصول'), 'danger')
            return redirect(url_for('salaries_statements'))
    except Exception:
        pass
    try:
        year = int(request.args.get('year'))
        month = int(request.args.get('month'))
    except Exception:
        flash(_('Select year and month / اختر السنة والشهر'), 'danger')
        return redirect(url_for('salaries_statements'))

    from sqlalchemy import func
    recs = Salary.query.filter_by(year=year, month=month).join(Employee).order_by(Employee.full_name.asc()).all()
    pays = db.session.query(Payment.invoice_id, func.coalesce(func.sum(Payment.amount_paid), 0)).\
        filter(Payment.invoice_type=='salary', Payment.invoice_id.in_([r.id for r in recs])).\
        group_by(Payment.invoice_id).all()
    paid_map = {pid: float(total or 0) for (pid,total) in pays}

    # Collect company name
    s = get_settings_safe()
    company_name = (s.company_name or '').strip() if s and s.company_name else 'Company'

    # HTML print (professional header) unless mode=pdf explicitly
    if request.args.get('mode') != 'pdf':
        # Prepare rows and totals for template
        rows = []
        totals = {
            'basic': 0.0, 'allow': 0.0, 'ded': 0.0, 'prev': 0.0, 'total': 0.0, 'paid': 0.0, 'remaining': 0.0
        }
        for s_row in recs:
            paid = paid_map.get(s_row.id, 0.0)
            total = float(s_row.total_salary or 0)
            remaining = max(total - paid, 0.0)
            rows.append({
                'employee_name': s_row.employee.full_name if s_row.employee else str(s_row.employee_id),
                'basic': float(s_row.basic_salary or 0),
                'allow': float(s_row.allowances or 0),
                'ded': float(s_row.deductions or 0),
                'prev': float(s_row.previous_salary_due or 0),
                'total': total,
                'paid': paid,
                'remaining': remaining,
                'status': s_row.status,
            })
            totals['basic'] += float(s_row.basic_salary or 0)
            totals['allow'] += float(s_row.allowances or 0)
            totals['ded'] += float(s_row.deductions or 0)
            totals['prev'] += float(s_row.previous_salary_due or 0)
            totals['total'] += total
            totals['paid'] += paid
            totals['remaining'] += remaining
        # Header data
        s = get_settings_safe()
        company_name = (s.company_name or '').strip() if s and s.company_name else 'Company'
        logo_url = url_for('static', filename='logo.svg', _external=False)
        title = _("Payroll Statements / كشوفات الرواتب")
        meta = _("Month / الشهر") + f": {year}-{month:02d}"
        header_note = _("Generated by System / تم التوليد بواسطة النظام")
        return render_template('print/payroll.html',
            title=title, company_name=company_name, logo_url=logo_url, header_note=header_note,
            meta=meta, rows=rows, totals=totals)

    # Try PDF via reportlab
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import io, os as _os

        def register_ar_font():
            candidates = [
                r"C:\\Windows\\Fonts\\trado.ttf",
                r"C:\\Windows\\Fonts\\Tahoma.ttf",
                r"C:\\Windows\\Fonts\\arial.ttf",
                "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
            for fp in candidates:
                if _os.path.exists(fp):
                    pdfmetrics.registerFont(TTFont('Arabic', fp))
                    return 'Arabic'
            return None
        def shape_ar(t):
            try:
                import arabic_reshaper
                from bidi.algorithm import get_display
                return get_display(arabic_reshaper.reshape(t))
            except Exception:
                return t

        buf = io.BytesIO()
        p = canvas.Canvas(buf, pagesize=A4)
        w, h = A4
        ar = register_ar_font()
        # Header
        if ar:
            p.setFont(ar, 14)
            p.drawString(20*mm, h-20*mm, shape_ar(company_name))
            p.setFont(ar, 11)
            p.drawString(20*mm, h-28*mm, shape_ar(f"كشف الرواتب لشهر {year}-{month:02d}"))
        else:
            p.setFont("Helvetica-Bold", 14)
            p.drawString(20*mm, h-20*mm, company_name)
            p.setFont("Helvetica", 11)
            p.drawString(20*mm, h-28*mm, f"Payroll Statement {year}-{month:02d}")

        # Table header
        y = h - 40*mm
        if ar:
            p.setFont(ar, 10)
            headers = ["الموظف","الأساسي","البدلات","الاستقطاعات","سابقة","الإجمالي","المدفوع","المتبقي","الحالة"]
            xcols = [20, 70, 95, 120, 145, 170, 195, 220, 245]
            for i, txt in enumerate(headers):
                p.drawString(xcols[i]*mm, y, shape_ar(txt))
        else:
            p.setFont("Helvetica", 10)
            headers = ["Employee","Basic","Allow","Deduct","Prev","Total","Paid","Remain","Status"]
            xcols = [20, 70, 95, 120, 145, 170, 195, 220, 245]
            for i, txt in enumerate(headers):
                p.drawString(xcols[i]*mm, y, txt)
        y -= 8*mm

        # Rows
        for s_row in recs:
            paid = paid_map.get(s_row.id, 0.0)
            total = float(s_row.total_salary or 0)
            remaining = max(total - paid, 0.0)
            vals = [
                s_row.employee.full_name if s_row.employee else str(s_row.employee_id),
                f"{float(s_row.basic_salary or 0):.2f}",
                f"{float(s_row.allowances or 0):.2f}",
                f"{float(s_row.deductions or 0):.2f}",
                f"{float(s_row.previous_salary_due or 0):.2f}",
                f"{total:.2f}", f"{paid:.2f}", f"{remaining:.2f}", s_row.status
            ]
            if ar:
                vals[0] = shape_ar(vals[0])
                vals[-1] = shape_ar(vals[-1])
            for i, v in enumerate(vals):
                p.drawString(xcols[i]*mm, y, v)
            y -= 7*mm
            if y < 20*mm:
                p.showPage(); y = h - 20*mm
                if ar: p.setFont(ar, 10)
                else: p.setFont("Helvetica", 10)

        p.showPage(); p.save(); buf.seek(0)
        return send_file(buf, as_attachment=False, download_name=f"Payroll_{year}-{month:02d}.pdf", mimetype='application/pdf')
    except Exception:
        # Fallback to HTML template for print
        return render_template('salaries_statements.html', year=year, month=month, rows=[{
            'id': r.id,
            'employee_name': r.employee.full_name if r.employee else str(r.employee_id),
            'basic': float(r.basic_salary or 0),
            'allow': float(r.allowances or 0),
            'ded': float(r.deductions or 0),
            'prev': float(r.previous_salary_due or 0),
            'total': float(r.total_salary or 0),
            'paid': paid_map.get(r.id, 0.0),
            'remaining': max(float(r.total_salary or 0) - paid_map.get(r.id, 0.0), 0.0),
            'status': r.status,
        } for r in recs], totals=None)


@app.route('/salaries/<int:salary_id>/delete', methods=['POST'])
@login_required
def delete_salary(salary_id):
    sal = Salary.query.get_or_404(salary_id)
    try:
        db.session.delete(sal)
        db.session.commit()
        flash(_('تم حذف الراتب / Salary deleted'), 'info')
    except Exception:
        db.session.rollback()
        flash(_('تعذر حذف الراتب / Could not delete salary'), 'danger')
    return redirect(url_for('salaries'))



# Salaries monthly management
@app.route('/salaries/monthly', methods=['GET', 'POST'])
@login_required
def salaries_monthly():
    from sqlalchemy import func
    # Permission: view
    try:
        if not (getattr(current_user,'role','')=='admin' or can_perm('salaries','view')):
            flash(_('You do not have permission / لا تملك صلاحية الوصول'), 'danger')
            return redirect(url_for('dashboard'))
    except Exception:
        pass
    # Select year/month
    try:
        year = int(request.values.get('year') or datetime.now(timezone.utc).year)
    except Exception:
        year = datetime.now(timezone.utc).year
    try:
        month = int(request.values.get('month') or datetime.now(timezone.utc).month)
    except Exception:
        month = datetime.now(timezone.utc).month

    # Ensure salary rows exist for all active employees
    emps = Employee.query.filter_by(status='active').order_by(Employee.full_name.asc()).all()
    existing = {(s.employee_id, s.year, s.month): s for s in Salary.query.filter_by(year=year, month=month).all()}
    created = 0
    for e in emps:
        if (e.id, year, month) not in existing:
            s = Salary(employee_id=e.id, year=year, month=month,
                       basic_salary=0, allowances=0, deductions=0, previous_salary_due=0,
                       total_salary=0, status='due')
            db.session.add(s)
            created += 1
    if created:
        db.session.commit()

    # Fetch salaries for period with payments summary
    salaries_q = Salary.query.filter_by(year=year, month=month).join(Employee).order_by(Employee.full_name.asc())
    salaries_list = salaries_q.all()

    # Payments sum per salary
    pays = db.session.query(Payment.invoice_id, func.coalesce(func.sum(Payment.amount_paid), 0)).\
        filter(Payment.invoice_type=='salary', Payment.invoice_id.in_([s.id for s in salaries_list])).\
        group_by(Payment.invoice_id).all()
    paid_map = {pid: float(total or 0) for (pid,total) in pays}

    # Prepare rows
    rows = []
    for s in salaries_list:
        paid = paid_map.get(s.id, 0.0)
        total = float(s.total_salary or 0)
        remaining = max(total - paid, 0.0)
        rows.append({
            'id': s.id,
            'employee_name': s.employee.full_name if s.employee else str(s.employee_id),
            'basic_salary': float(s.basic_salary or 0),
            'allowances': float(s.allowances or 0),
            'deductions': float(s.deductions or 0),
            'previous_salary_due': float(s.previous_salary_due or 0),
            'total_salary': total,
            'status': s.status,
            'paid': paid,
            'remaining': remaining,
        })

    return render_template('salaries_monthly.html', year=year, month=month, rows=rows)

@app.route('/salaries/monthly/save', methods=['POST'])
@login_required
def salaries_monthly_save():
    from sqlalchemy import func
    # Permission: edit
    try:
        if not (getattr(current_user,'role','')=='admin' or can_perm('salaries','edit')):
            flash(_('You do not have permission / لا تملك صلاحية الوصول'), 'danger')
            return redirect(url_for('salaries_monthly', year=request.form.get('year'), month=request.form.get('month')))
    except Exception:
        pass
    # Expect fields like basic_salary_<id>, allowances_<id>, deductions_<id>, previous_salary_due_<id>
    updated = 0
    for key, val in request.form.items():
        try:
            if '_' not in key: continue
            field, sid_str = key.rsplit('_', 1)
            sid = int(sid_str)
            s = Salary.query.get(sid)
            if not s: continue
            if field in ['basic_salary','allowances','deductions','previous_salary_due']:
                try:
                    num = float((val or '0').replace(',', '.'))
                except Exception:
                    num = 0.0
                setattr(s, field, num)
                # Recompute total
                s.total_salary = float(s.basic_salary or 0) + float(s.allowances or 0) - float(s.deductions or 0) + float(s.previous_salary_due or 0)
                # Update status based on payments
                paid = float(db.session.query(func.coalesce(func.sum(Payment.amount_paid), 0)).\
                    filter_by(invoice_type='salary', invoice_id=s.id).scalar() or 0)
                s.status = 'paid' if paid >= float(s.total_salary or 0) else ('partial' if paid > 0 else 'due')
                updated += 1
        except Exception:
            continue
    if updated:
        db.session.commit()
        flash(_('تم حفظ التعديلات / Changes saved'), 'success')
    else:
        flash(_('No changes / لا توجد تعديلات'), 'info')
    return redirect(url_for('salaries_monthly', year=request.form.get('year'), month=request.form.get('month')))

@app.route('/settings/print', methods=['POST'])
@login_required
def settings_print_save():
    from models import Settings
    s = Settings.query.first()
    if not s:
        s = Settings()
        db.session.add(s)
    s.receipt_paper_width = (request.form.get('receipt_paper_width') or '80')
    s.receipt_margin_top_mm = int(request.form.get('receipt_margin_top_mm') or 5)
    s.receipt_margin_bottom_mm = int(request.form.get('receipt_margin_bottom_mm') or 5)
    s.receipt_margin_left_mm = int(request.form.get('receipt_margin_left_mm') or 3)
    s.receipt_margin_right_mm = int(request.form.get('receipt_margin_right_mm') or 3)
    s.receipt_font_size = int(request.form.get('receipt_font_size') or 12)
    s.receipt_show_logo = bool(request.form.get('receipt_show_logo'))
    s.receipt_show_tax_number = bool(request.form.get('receipt_show_tax_number'))
    s.receipt_footer_text = (request.form.get('receipt_footer_text') or '').strip()
    db.session.commit()
    flash(_('Print settings saved / تم حفظ إعدادات الطباعة'), 'success')
    return redirect(url_for('settings'))


# Legacy /vat route redirects to the new VAT dashboard
@app.route('/vat')
@login_required
def vat():
    return redirect(url_for('vat.vat_dashboard'))


# Deprecated placeholder route kept for backward compatibility
@app.route('/financials')
@login_required
def financials():
    return redirect(url_for('financials.income_statement'))

@app.route('/settings', methods=['GET','POST'])
@login_required
def settings():
    from models import Settings
    s = Settings.query.first()
    if request.method == 'POST':
        if not s:
            s = Settings()
            db.session.add(s)
        s.company_name = request.form.get('company_name')
        s.tax_number = request.form.get('tax_number')
        s.address = request.form.get('address')
        s.phone = request.form.get('phone')
        s.email = request.form.get('email')
        try:
            s.vat_rate = float(request.form.get('vat_rate') or 15)
        except Exception:
            s.vat_rate = 15.0
        s.currency = request.form.get('currency') or 'SAR'
        s.place_india_label = request.form.get('place_india_label') or 'Place India'
        s.china_town_label = request.form.get('china_town_label') or 'China Town'
        s.default_theme = (request.form.get('default_theme') or 'light').lower()
        # Receipt settings
        s.receipt_paper_width = (request.form.get('receipt_paper_width') or s.receipt_paper_width or '80')
        try:
            s.receipt_font_size = int(request.form.get('receipt_font_size') or s.receipt_font_size or 12)
        except Exception:
            pass
        # New configurable fields
        try:
            s.receipt_logo_height = int(request.form.get('receipt_logo_height') or (s.receipt_logo_height or 40))
        except Exception:
            pass
        try:
            s.receipt_extra_bottom_mm = int(request.form.get('receipt_extra_bottom_mm') or (s.receipt_extra_bottom_mm or 15))
        except Exception:
            pass
        # Handle logo upload
        if 'logo_file' in request.files and request.files['logo_file'].filename:
            logo_file = request.files['logo_file']
            if logo_file and logo_file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg')):
                try:
                    import os
                    from werkzeug.utils import secure_filename

                    # Create uploads directory if it doesn't exist
                    upload_dir = os.path.join(app.static_folder, 'uploads')
                    os.makedirs(upload_dir, exist_ok=True)

                    # Generate unique filename
                    filename = secure_filename(logo_file.filename)
                    timestamp = str(int(time.time()))
                    name, ext = os.path.splitext(filename)
                    unique_filename = f"logo_{timestamp}{ext}"

                    # Save file
                    file_path = os.path.join(upload_dir, unique_filename)
                    logo_file.save(file_path)

                    # Update logo URL to point to uploaded file
                    s.logo_url = f'/static/uploads/{unique_filename}'
                    flash(_('Logo uploaded successfully / تم رفع الشعار بنجاح'), 'success')

                except Exception as e:
                    flash(_('Failed to upload logo / فشل رفع الشعار: %(error)s', error=str(e)), 'danger')
        else:
            # Use URL if no file uploaded
            s.logo_url = (request.form.get('logo_url') or s.logo_url or '/static/chinese-logo.svg')

        s.receipt_show_logo = bool(request.form.get('receipt_show_logo'))
        s.receipt_show_tax_number = bool(request.form.get('receipt_show_tax_number'))
        s.receipt_footer_text = (request.form.get('receipt_footer_text') or s.receipt_footer_text or '')
        db.session.commit()
        flash(_('Settings saved successfully / تم حفظ الإعدادات'), 'success')
        return redirect(url_for('settings'))
    return render_template('settings.html', s=s or Settings())

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    current = (request.form.get('current_password') or '').strip()
    new = (request.form.get('new_password') or '').strip()
    confirm = (request.form.get('confirm_password') or '').strip()
    # Validate
    if not current or not new or not confirm:
        flash(_('Please fill all fields / الرجاء تعبئة جميع الحقول'), 'danger')
        return redirect(url_for('settings'))
    if new != confirm:
        flash(_('New passwords do not match / كلمتا المرور غير متطابقتين'), 'danger')
        return redirect(url_for('settings'))
    if new == current:
        flash(_('New password must be different from current / يجب أن تكون كلمة المرور الجديدة مختلفة عن الحالية'), 'danger')
        return redirect(url_for('settings'))
    # Verify current against fresh DB state
    try:
        u = User.query.get(current_user.id)
    except Exception:
        u = None
    if not u or not bcrypt.check_password_hash(u.password_hash, current):
        flash(_('Current password is incorrect / كلمة المرور الحالية غير صحيحة'), 'danger')
        return redirect(url_for('settings'))
    # Update securely
    u.set_password(new, bcrypt)
    try:
        db.session.commit()
        # Sync session object
        try:
            current_user.password_hash = u.password_hash
        except Exception:
            pass
        flash(_('Password updated successfully / تم تحديث كلمة المرور بنجاح'), 'success')
    except Exception as e:
        db.session.rollback()
        flash(_('Unexpected error. Please try again / حدث خطأ غير متوقع، حاول مرة أخرى'), 'danger')
    return redirect(url_for('settings'))


# ---- Simple permission checker usable in routes (Python scope)
from models import UserPermission

def can_perm(screen, perm, branch_scope=None):
    try:
        if getattr(current_user,'role','') == 'admin':
            return True
        q = UserPermission.query.filter_by(user_id=current_user.id, screen_key=screen)
        # Branch-aware: allow if permission exists for this branch or for 'all'
        for p in q.all():
            if branch_scope and p.branch_scope not in (branch_scope, 'all', None):
                continue
            if perm == 'view' and p.can_view: return True
            if perm == 'add' and p.can_add: return True
            if perm == 'edit' and p.can_edit: return True
            if perm == 'delete' and p.can_delete: return True
            if perm == 'print' and p.can_print: return True
    except Exception:
        pass
    return False

def first_allowed_sales_branch():
    try:
        if getattr(current_user,'role','') == 'admin':
            return 'all'
        perms = UserPermission.query.filter_by(user_id=current_user.id, screen_key='sales').all()
        scopes = [p.branch_scope for p in perms if p.can_view]
        if not scopes:
            return None
        if 'all' in scopes or None in scopes:
            return 'all'
        # return first specific branch
        return scopes[0]
    except Exception:
        return None


BRANCH_CODES = {'china_town': 'China Town', 'place_india': 'Place India'}

def is_valid_branch(code:str)->bool:
    return code in BRANCH_CODES

def branch_label(code:str)->str:
    return BRANCH_CODES.get(code, code)

# ---------------------- Users API ----------------------
@app.route('/api/users', methods=['GET'])
@login_required
def api_users_list():
    if not can_perm('users','view'):
        return jsonify({'error':'forbidden'}), 403
    q = (request.args.get('q') or '').strip().lower()
    page = int(request.args.get('page') or 1)
    per_page = min(50, int(request.args.get('per_page') or 10))
    sort = request.args.get('sort') or 'username'
    query = User.query
    if q:
        query = query.filter((User.username.ilike(f'%{q}%')) | (User.email.ilike(f'%{q}%')))
    if sort in ['username','email','role','active']:
        query = query.order_by(getattr(User, sort).asc())
    pag = query.paginate(page=page, per_page=per_page, error_out=False)
    data = [
        {'id':u.id,'username':u.username,'email':u.email,'role':u.role,'active':u.active}
        for u in pag.items
    ]
    return jsonify({'items':data,'page':pag.page,'pages':pag.pages,'total':pag.total})

@app.route('/api/users', methods=['POST'])
@login_required
def api_users_create():
    if not can_perm('users','add'):
        return jsonify({'error':'forbidden'}), 403
    payload = request.get_json(force=True) or {}
    username = (payload.get('username') or '').strip()
    email = (payload.get('email') or '').strip() or None
    role = (payload.get('role') or 'user').strip()
    password = (payload.get('password') or '').strip()
    if not username or not password:
        return jsonify({'error':'username and password required'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'error':'username already exists'}), 400
    u = User(username=username, email=email, role=role, active=True)
    u.set_password(password, bcrypt)
    db.session.add(u)
    db.session.commit()
    return jsonify({'status':'ok','id':u.id})

@app.route('/api/users/<int:uid>', methods=['PATCH'])
@login_required
def api_users_update(uid):
    u = User.query.get_or_404(uid)
    payload = request.get_json(force=True) or {}
    for field in ['email','role']:
        if field in payload:
            setattr(u, field, payload[field])
    if 'active' in payload:
        u.active = bool(payload['active'])
    if 'password' in payload and payload['password']:
        u.set_password(payload['password'], bcrypt)
    db.session.commit()
    return jsonify({'status':'ok'})

@app.route('/api/users', methods=['DELETE'])
@login_required
def api_users_delete():
    if not can_perm('users','delete'):
        return jsonify({'error':'forbidden'}), 403
    payload = request.get_json(force=True) or {}
    ids = payload.get('ids') or []
    if not ids:
        return jsonify({'error':'no ids'}), 400
    User.query.filter(User.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({'status':'ok','deleted':len(ids)})

# ----- Permissions enforcement helpers -----
from functools import wraps
from flask import abort

def user_has_perm(user, screen_key:str, perm:str)->bool:
    try:
        if getattr(user, 'role', '') == 'admin':
            return True
        from models import UserPermission
        q = UserPermission.query.filter_by(user_id=user.id, screen_key=screen_key)
        # If any scope grants the permission, allow
        for p in q.all():
            if perm == 'view' and p.can_view: return True
            if perm == 'add' and p.can_add: return True
            if perm == 'edit' and p.can_edit: return True
            if perm == 'delete' and p.can_delete: return True
            if perm == 'print' and p.can_print: return True
    except Exception:
        pass
    return False

def require_perm(screen_key:str, perm:str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if getattr(current_user, 'role', '') == 'admin' or user_has_perm(current_user, screen_key, perm):
                return fn(*args, **kwargs)
            # API vs Page
            if request.path.startswith('/api/'):
                return jsonify({'error':'forbidden', 'detail': f'missing {screen_key}:{perm}'}), 403
            flash(_('You do not have permission / لا تملك صلاحية الوصول'), 'danger')
            return redirect(url_for('dashboard'))
        return wrapper
    return decorator

@app.context_processor
def inject_can():
    return dict(
        can=lambda screen,perm: (getattr(current_user,'role','')=='admin') or user_has_perm(current_user, screen, perm),
        can_branch=lambda screen,perm,branch_scope: can_perm(screen, perm, branch_scope)
    )

# ---------------------- Permissions API ----------------------
from models import UserPermission

@app.route('/api/users/<int:uid>/permissions', methods=['GET'])
@login_required
def api_user_permissions_get(uid):
    if not can_perm('users','view'):
        return jsonify({'error':'forbidden'}), 403
    User.query.get_or_404(uid)
    scope = request.args.get('branch_scope')
    q = UserPermission.query.filter_by(user_id=uid)
    if scope:
        q = q.filter_by(branch_scope=scope)
    perms = q.all()
    out = [
        {
            'screen_key': p.screen_key,
            'branch_scope': p.branch_scope,
            'view': p.can_view,
            'add': p.can_add,
            'edit': p.can_edit,
            'delete': p.can_delete,
            'print': p.can_print,
        } for p in perms
    ]
    return jsonify({'items': out})

@app.route('/api/users/<int:uid>/permissions', methods=['POST'])
@login_required
def api_user_permissions_save(uid):
    if not can_perm('users','edit'):
        return jsonify({'error':'forbidden'}), 403
    User.query.get_or_404(uid)
    payload = request.get_json(force=True) or {}
    items = payload.get('items') or []
    branch_scope = (payload.get('branch_scope') or 'all').lower()
    # Remove existing for this branch scope, then insert new
    UserPermission.query.filter_by(user_id=uid, branch_scope=branch_scope).delete(synchronize_session=False)
    for it in items:
        key = (it.get('screen_key') or '').strip()
        if not key: continue
        p = UserPermission(
            user_id=uid, screen_key=key, branch_scope=branch_scope,
            can_view=bool(it.get('view')), can_add=bool(it.get('add')),
            can_edit=bool(it.get('edit')), can_delete=bool(it.get('delete')),
            can_print=bool(it.get('print'))
        )
        db.session.add(p)
    db.session.commit()
    return jsonify({'status':'ok','count':len(items)})


# Retention: 12 months with PDF export
@app.route('/invoices/retention', methods=['GET'], endpoint='invoices_retention')
@login_required
def invoices_retention_view():
    # Show invoices older than 12 months (approx 365 days)
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=365)
    sales_old = SalesInvoice.query.filter(SalesInvoice.date < cutoff).order_by(SalesInvoice.date.desc()).limit(200).all()
    purchases_old = PurchaseInvoice.query.filter(PurchaseInvoice.date < cutoff).order_by(PurchaseInvoice.date.desc()).limit(200).all()
    expenses_old = ExpenseInvoice.query.filter(ExpenseInvoice.date < cutoff).order_by(ExpenseInvoice.date.desc()).limit(200).all()
    return render_template('retention.html', cutoff=cutoff, sales=sales_old, purchases=purchases_old, expenses=expenses_old)

@app.route('/invoices/retention/export', endpoint='invoices_retention_export')
@login_required
def invoices_retention_export_view():
    # Export invoices older than 12 months to a single PDF (summary style)
    from flask import send_file
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    import io
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=365)
    kind = (request.args.get('type') or 'all').lower()
    # Collect
    sales = SalesInvoice.query.filter(SalesInvoice.date < cutoff).order_by(SalesInvoice.date.asc()).all() if kind in ['all','sales'] else []
    purchases = PurchaseInvoice.query.filter(PurchaseInvoice.date < cutoff).order_by(PurchaseInvoice.date.asc()).all() if kind in ['all','purchase','purchases'] else []
    expenses = ExpenseInvoice.query.filter(ExpenseInvoice.date < cutoff).order_by(ExpenseInvoice.date.asc()).all() if kind in ['all','expense','expenses'] else []

    buf = io.BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    # Optional Arabic font shaper reused
    def shape_ar(t):
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            return get_display(arabic_reshaper.reshape(str(t)))
        except Exception:
            return str(t)

    y = h - 40
    p.setTitle(f"Invoices older than {cutoff}")
    p.setFont("Helvetica-Bold", 14)
    p.drawString(40, y, f"Invoices older than {cutoff}")
    y -= 30

    def line(txt, size=10):
        nonlocal y
        if y < 40:
            p.showPage(); y = h - 40; p.setFont("Helvetica", size)
        p.setFont("Helvetica", size)
        p.drawString(40, y, txt)
        y -= 16

    total_count = 0
    for inv in sales:
        total_count += 1
        line(f"[SALES] {inv.invoice_number} | {inv.date} | {inv.branch} | PM: {inv.payment_method} | Total: {float(inv.total_after_tax_discount or 0):.2f}")
    for inv in purchases:
        total_count += 1
        name = getattr(inv, 'supplier_name', '-')
        line(f"[PURCHASE] {inv.invoice_number} | {inv.date} | {shape_ar(name)} | PM: {inv.payment_method} | Total: {float(inv.total_after_tax_discount or 0):.2f}")
    for inv in expenses:
        total_count += 1
        line(f"[EXPENSE] {inv.invoice_number} | {inv.date} | PM: {inv.payment_method} | Total: {float(inv.total_after_tax_discount or 0):.2f}")

    if total_count == 0:
        line("No invoices older than 12 months / لا توجد فواتير أقدم من 12 شهراً", size=12)

    p.showPage(); p.save(); buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"invoices_retention_{cutoff}.pdf", mimetype='application/pdf')

@app.route('/users')
@require_perm('users','view')
def users():
    us = User.query.order_by(User.username.asc()).all()
    return render_template('users.html', users=us)

# Invoice management routes
@app.route('/invoices/print/<string:section>')
@login_required
def print_invoices(section):
    from flask import make_response
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    import io

    # Build rows from specialized invoice tables to avoid reliance on unified Invoice table
    from models import SalesInvoice, PurchaseInvoice, ExpenseInvoice
    section_norm = (section or 'all').lower()
    if section_norm in ['purchases', 'purchase']: section_norm = 'purchase'
    elif section_norm in ['expenses', 'expense']: section_norm = 'expense'
    elif section_norm in ['sales', 'sale']: section_norm = 'sales'
    else: section_norm = 'all'
    rows = []
    if section_norm in ['all','sales']:
        for s in SalesInvoice.query.order_by(SalesInvoice.date.desc()).all():
            rows.append({'invoice_number': s.invoice_number, 'who': s.customer_name or '-', 'total': float(s.total_after_tax_discount or 0), 'status': s.status})
    if section_norm in ['all','purchase']:
        for p in PurchaseInvoice.query.order_by(PurchaseInvoice.date.desc()).all():
            rows.append({'invoice_number': p.invoice_number, 'who': p.supplier_name or '-', 'total': float(p.total_after_tax_discount or 0), 'status': p.status})
    if section_norm in ['all','expense']:
        for e in ExpenseInvoice.query.order_by(ExpenseInvoice.date.desc()).all():
            rows.append({'invoice_number': e.invoice_number, 'who': '-', 'total': float(e.total_after_tax_discount or 0), 'status': e.status})

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    y = 800

    # Helpers: register Arabic-capable font and shape Arabic text if libs exist
    def register_ar_font():
        try:
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            import os as _os
            candidates = [
                r"C:\\Windows\\Fonts\\trado.ttf",  # Traditional Arabic (Windows)
                r"C:\\Windows\\Fonts\\arial.ttf",
                r"C:\\Windows\\Fonts\\Tahoma.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
            ]
            for fp in candidates:
                if _os.path.exists(fp):
                    pdfmetrics.registerFont(TTFont('Arabic', fp))
                    return 'Arabic'
        except Exception:
            pass
        return None

    def shape_ar(text:str)->str:
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            return get_display(arabic_reshaper.reshape(text))
        except Exception:
            return text

    # Header with company name
    try:
        from models import Settings
        s = Settings.query.first()
        company_name = (s.company_name or '').strip() if s and s.company_name else ''
    except Exception:
        company_name = ''

    ar_font = register_ar_font()
    if ar_font:
        p.setFont(ar_font, 14)
        p.drawString(40, y, shape_ar(company_name or "Company"))
        y -= 22
        p.setFont(ar_font, 12)
        p.drawString(40, y, shape_ar(f"Invoices - {section_norm.title()}"))
    else:
        p.setFont("Helvetica-Bold", 14)
        p.drawString(40, y, company_name or "Company")
        y -= 22
        p.setFont("Helvetica", 12)
        p.drawString(40, y, f"Invoices - {section_norm.title()}")
    y -= 20

    # Table header
    if ar_font:
        p.setFont(ar_font, 11)
    else:
        p.setFont("Helvetica-Bold", 11)
    p.drawString(40, y, shape_ar("Invoice"))
    p.drawString(140, y, shape_ar("Who"))
    p.drawRightString(380, y, shape_ar("Total"))
    p.drawString(400, y, shape_ar("Status"))
    y -= 14
    p.line(40, y, 520, y)
    y -= 10

    # Body rows
    if ar_font:
        p.setFont(ar_font, 10)
    else:
        p.setFont("Helvetica", 10)
    for r in rows:
        if y < 60:
            p.showPage()
            if ar_font:
                p.setFont(ar_font, 10)
            else:
                p.setFont("Helvetica", 10)
            y = 800
        p.drawString(40, y, shape_ar(str(r.get('invoice_number') or '')))
        p.drawString(140, y, shape_ar(str(r.get('who') or '-')))
        p.drawRightString(380, y, f"{float(r.get('total') or 0):.2f}")
        status = str(r.get('status') or '').title()
        p.drawString(400, y, shape_ar(status))
        y -= 14

    p.showPage()
    p.save()
    buffer.seek(0)
    return make_response(buffer.getvalue(), 200, {
        'Content-Type': 'application/pdf',
        'Content-Disposition': f'inline; filename="invoices_{section_norm}.pdf"'
    })

@app.route('/sales/<int:invoice_id>/print', methods=['GET'])
@login_required
def print_sales_receipt(invoice_id:int):
    # Receipt-style (80mm) print for a single sales invoice
    inv = SalesInvoice.query.get_or_404(invoice_id)
    items = SalesInvoiceItem.query.filter_by(invoice_id=invoice_id).all()
    try:
        from models import Settings
        s = Settings.query.first()
        company_name = (s.company_name or '').strip() if s and s.company_name else 'Company'
        tax_number = (s.tax_number or '').strip() if s and s.tax_number else None
        phone = (s.phone or '').strip() if s and s.phone else None
        currency = s.currency if s and s.currency else 'SAR'
    except Exception:
        company_name, tax_number, phone, currency = 'Company', None, None, 'SAR'
    logo_url = url_for('static', filename='logo.svg', _external=False)
    return render_template('print/receipt.html',
        company_name=company_name,
        tax_number=tax_number,
        phone=phone,
        currency=currency,
        logo_url=logo_url,
        inv=inv,
        items=items,
    )

    # Body rows
    if ar_font:
        p.setFont(ar_font, 10)
    else:
        p.setFont("Helvetica", 10)
    for r in rows:
        line = f"{r['invoice_number']} | {r['who']} | {r['total']:.2f} | {r['status']}"
        p.drawString(50, y, shape_ar(line) if ar_font else line)
        y -= 20
        if y < 50:  # New page if needed
            p.showPage()
            y = 800
            if ar_font:
                p.setFont(ar_font, 10)
            else:
                p.setFont("Helvetica", 10)

    p.showPage()
    p.save()

    buffer.seek(0)
    return make_response(buffer.getvalue(), 200, {
        'Content-Type': 'application/pdf',
        'Content-Disposition': f'inline; filename="{section}_invoices.pdf"'
    })

@app.route('/invoices/single_payment/<int:invoice_id>', methods=['POST'])
@login_required
def single_payment(invoice_id):
    # Single payment against unified Invoice table (legacy). If not exists, fall back to specialized tables mapping.
    try:
        invoice = Invoice.query.get_or_404(invoice_id)
    except Exception:
        # Fallback: attempt to locate in specialized invoices (use first match by id) and mirror minimal fields
        from models import SalesInvoice, PurchaseInvoice, ExpenseInvoice
        invoice = SalesInvoice.query.get(invoice_id) or PurchaseInvoice.query.get(invoice_id) or ExpenseInvoice.query.get(invoice_id)
        if not invoice:
            abort(404)
    payment_amount = float(request.form.get('payment_amount', 0))

    if payment_amount > 0:
        invoice.paid_amount += payment_amount
        invoice.update_status()
        db.session.commit()

        # Emit real-time update
        socketio.emit('invoice_update', {
            'invoice_id': invoice_id,
            'new_status': invoice.status,
            'paid_amount': invoice.paid_amount
        })

        flash(_('Payment recorded successfully / تم تسجيل الدفعة بنجاح'), 'success')

    return redirect(url_for('invoices'))

@app.route('/invoices/bulk_payment', methods=['POST'])
@login_required
def bulk_payment():
    invoice_ids = request.form.getlist('invoice_ids')
    bulk_payment_amount = float(request.form.get('bulk_payment_amount', 0))

    if invoice_ids and bulk_payment_amount > 0:
        # Distribute payment equally among selected invoices
        payment_per_invoice = bulk_payment_amount / len(invoice_ids)

        for invoice_id in invoice_ids:
            invoice = Invoice.query.get(int(invoice_id))
            if invoice:
                invoice.paid_amount += payment_per_invoice
                invoice.update_status()

        db.session.commit()

        # Emit real-time update
        socketio.emit('invoice_update', {
            'bulk_update': True,
            'updated_invoices': invoice_ids
        })

        flash(_('Bulk payment recorded successfully / تم تسجيل الدفعة الجماعية بنجاح'), 'success')

    return redirect(url_for('invoices'))

# Raw Materials Management
@app.route('/raw_materials', methods=['GET', 'POST'])
@login_required
def raw_materials():
    form = RawMaterialForm()

    if form.validate_on_submit():
        raw_material = RawMaterial(
            name=form.name.data,
            name_ar=form.name_ar.data,
            unit=form.unit.data,
            cost_per_unit=form.cost_per_unit.data,
            category=form.category.data,
            active=True
        )
        db.session.add(raw_material)
        db.session.commit()

        flash(_('Raw material added successfully / تم إضافة المادة الخام بنجاح'), 'success')
        return redirect(url_for('raw_materials'))

    materials = RawMaterial.query.filter_by(active=True).all()
    return render_template('raw_materials.html', form=form, materials=materials)

# Meals Management
@app.route('/meals', methods=['GET', 'POST'])
@login_required
def meals():
    import json

    # Get raw materials for dropdown
    raw_materials = RawMaterial.query.filter_by(active=True).all()
    material_choices = [(0, _('Select Ingredient / اختر المكون'))] + [(m.id, m.display_name) for m in raw_materials]

    form = MealForm()

    # Set material choices for all ingredient forms
    for ingredient_form in form.ingredients:
        ingredient_form.raw_material_id.choices = material_choices

    # Prepare materials JSON for JavaScript cost calculation
    materials_json = json.dumps([{
        'id': m.id,
        'name': m.display_name,
        'cost_per_unit': float(m.cost_per_unit),
        'unit': m.unit
    } for m in raw_materials])

    if form.validate_on_submit():
        try:
            # Create meal
            meal = Meal(
                name=form.name.data,
                name_ar=form.name_ar.data,
                description=form.description.data,
                category=form.category.data,
                profit_margin_percent=form.profit_margin_percent.data,
                user_id=current_user.id
            )
            db.session.add(meal)
            db.session.flush()  # Get meal ID

            # Add ingredients and calculate total cost (robust parse from POST to support dynamic rows)
            from decimal import Decimal
            total_cost = 0
            # Find all indices in POST like ingredients-<i>-raw_material_id
            idxs = set()
            for k in request.form.keys():
                if k.startswith('ingredients-') and k.endswith('-raw_material_id'):
                    try:
                        idxs.add(int(k.split('-')[1]))
                    except Exception:
                        pass
            for i in sorted(idxs):
                try:
                    rm_id = int(request.form.get(f'ingredients-{i}-raw_material_id') or 0)
                    qty_raw = request.form.get(f'ingredients-{i}-quantity')
                    qty = Decimal(qty_raw) if qty_raw not in (None, '',) else Decimal('0')
                except Exception:
                    rm_id, qty = 0, Decimal('0')
                if rm_id and qty > 0:
                    raw_material = RawMaterial.query.get(rm_id)
                    if raw_material:
                        ingredient = MealIngredient(
                            meal_id=meal.id,
                            raw_material_id=raw_material.id,
                            quantity=qty
                        )
                        # Compute cost directly using the fetched raw_material to avoid lazy-load issues
                        try:
                            from decimal import Decimal
                            ing_cost = qty * raw_material.cost_per_unit
                            ingredient.total_cost = ing_cost
                        except Exception:
                            ingredient.total_cost = 0
                        db.session.add(ingredient)
                        total_cost += float(ingredient.total_cost)

            # Update meal costs
            meal.total_cost = total_cost
            meal.calculate_selling_price()

            db.session.commit()

            # Emit real-time update
            socketio.emit('meal_update', {
                'meal_name': meal.display_name,
                'total_cost': float(meal.total_cost),
                'selling_price': float(meal.selling_price)
            })

            flash(_('Meal created successfully / تم إنشاء الوجبة بنجاح'), 'success')
            return redirect(url_for('meals'))
        except Exception as e:
            db.session.rollback()
            logging.exception('Failed to save meal')
            flash(_('Failed to save meal / فشل حفظ الوجبة'), 'danger')

    # Get all meals
    all_meals = Meal.query.filter_by(active=True).all()
    return render_template('meals.html', form=form, meals=all_meals, materials_json=materials_json)

# Delete routes
@app.route('/delete_raw_material/<int:material_id>', methods=['POST'])
@login_required
def delete_raw_material(material_id):
    material = RawMaterial.query.get_or_404(material_id)

    # Check if material is used in any meals
    meals_using_material = MealIngredient.query.filter_by(raw_material_id=material_id).all()
    if meals_using_material:
        meal_names = [ingredient.meal.display_name for ingredient in meals_using_material]
        flash(_('Cannot delete material. It is used in meals: {}').format(', '.join(meal_names)), 'error')
        return redirect(url_for('raw_materials'))

    # Check if material is used in any purchase invoices
    purchase_items = PurchaseInvoiceItem.query.filter_by(raw_material_id=material_id).all()
    if purchase_items:
        flash(_('Cannot delete material. It has purchase history. Material will be deactivated instead.'), 'warning')
        material.active = False
    else:
        db.session.delete(material)

    db.session.commit()
    flash(_('Raw material deleted successfully / تم حذف المادة الخام بنجاح'), 'success')
    return redirect(url_for('raw_materials'))

@app.route('/delete_meal/<int:meal_id>', methods=['POST'])
@login_required
def delete_meal(meal_id):
    meal = Meal.query.get_or_404(meal_id)

    # Check if meal is used in any sales invoices
    sales_items = SalesInvoiceItem.query.filter_by(product_name=meal.display_name).all()
    if sales_items:
        flash(_('Cannot delete meal. It has sales history. Meal will be deactivated instead.'), 'warning')
        meal.active = False
    else:
        # Delete meal ingredients first
        MealIngredient.query.filter_by(meal_id=meal_id).delete()
        db.session.delete(meal)

    db.session.commit()
    flash(_('Meal deleted successfully / تم حذف الوجبة بنجاح'), 'success')
    return redirect(url_for('meals'))

@app.route('/delete_purchase_invoice/<int:invoice_id>', methods=['POST'])
@login_required
def delete_purchase_invoice(invoice_id):
    invoice = PurchaseInvoice.query.get_or_404(invoice_id)

    # Reverse stock updates
    for item in invoice.items:
        raw_material = item.raw_material
        if raw_material:
            # Reduce stock quantity
            raw_material.stock_quantity -= item.quantity

            # Recalculate weighted average cost (simplified approach)
            # In a real system, you might want to track cost history more precisely
            if raw_material.stock_quantity <= 0:
                raw_material.stock_quantity = 0
                # Keep the last known cost

    # Delete invoice items first
    PurchaseInvoiceItem.query.filter_by(invoice_id=invoice_id).delete()

    # Delete invoice
    db.session.delete(invoice)
    db.session.commit()

    flash(_('Purchase invoice deleted and stock updated / تم حذف فاتورة الشراء وتحديث المخزون'), 'success')
    return redirect(url_for('purchases'))

@app.route('/delete_sales_invoice/<int:invoice_id>', methods=['POST'])
@login_required
def delete_sales_invoice(invoice_id):
    invoice = SalesInvoice.query.get_or_404(invoice_id)

    # Delete related payments first
    try:
        Payment.query.filter_by(invoice_id=invoice_id, invoice_type='sales').delete()
    except:
        pass  # Payment table might not exist in some setups

    # Delete invoice items first
    SalesInvoiceItem.query.filter_by(invoice_id=invoice_id).delete()

    # Delete invoice
    db.session.delete(invoice)
    db.session.commit()

    flash(_('Sales invoice deleted successfully / تم حذف فاتورة المبيعات بنجاح'), 'success')

    # Check if request came from payments page
    referer = request.headers.get('Referer', '')
    if 'payments' in referer:
        return redirect(url_for('payments'))
    else:
        return redirect(url_for('sales'))

@app.route('/delete_expense_invoice/<int:invoice_id>', methods=['POST'])
@login_required
def delete_expense_invoice(invoice_id):
    invoice = ExpenseInvoice.query.get_or_404(invoice_id)

    # Delete related payments first
    try:
        Payment.query.filter_by(invoice_id=invoice_id, invoice_type='expense').delete()
    except:
        pass

    # Delete invoice items first
    ExpenseInvoiceItem.query.filter_by(invoice_id=invoice_id).delete()

    # Delete invoice
    db.session.delete(invoice)
    db.session.commit()

    flash(_('Expense invoice deleted successfully / تم حذف فاتورة المصروفات بنجاح'), 'success')

    # Check if request came from payments page
    referer = request.headers.get('Referer', '')
    if 'payments' in referer:
        return redirect(url_for('payments'))
    else:
        return redirect(url_for('expenses'))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=8000, debug=True)

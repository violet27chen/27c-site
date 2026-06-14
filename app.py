#!/usr/bin/env python3
"""
27c.site - Cloud Resource Hub
Flask application with multi-cloud support
"""

import os
import hashlib
import time
import secrets
import functools

import pymysql
import pymysql.cursors
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g, make_response
)
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv

from translations import get_translations, t as tr

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# ─── App Configuration ────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'fallback-key-change-me')
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7 days

bcrypt = Bcrypt(app)

# ─── Register Quark Blueprint ─────────────────────────────────────────
from quark_routes import quark_bp
app.register_blueprint(quark_bp)

# ─── Database Configuration ───────────────────────────────────────────
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'user': os.environ.get('DB_USER', 'shopuser'),
    'password': os.environ.get('DB_PASS', ''),
    'database': os.environ.get('DB_NAME', 'software_shop'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
}


# ─── Language Support ─────────────────────────────────────────────────
@app.before_request
def detect_language():
    lang = request.args.get('lang')
    if lang in ('zh', 'en'):
        g.lang = lang
        return
    lang = request.cookies.get('site_lang')
    if lang in ('zh', 'en'):
        g.lang = lang
        return
    g.lang = 'zh'


@app.route('/setlang/<lang>')
def set_lang(lang):
    if lang not in ('zh', 'en'):
        lang = 'zh'
    resp = make_response(redirect(request.referrer or url_for('index')))
    resp.set_cookie('site_lang', lang, max_age=86400 * 365)
    return resp


@app.context_processor
def inject_lang():
    try:
        cur_lang = g.lang
    except Exception:
        cur_lang = 'zh'

    def translate(key, **kwargs):
        return tr(cur_lang, key, **kwargs)

    return dict(lang=cur_lang, t=translate)


# ─── Database Helpers ─────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = pymysql.connect(**DB_CONFIG)
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def query_db(sql, args=None, one=False):
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(sql, args)
        if one:
            return cursor.fetchone()
        return cursor.fetchall()


def modify_db(sql, args=None):
    db = get_db()
    with db.cursor() as cursor:
        cursor.execute(sql, args)
    db.commit()
    return cursor.lastrowid


# ─── Auth Helpers ─────────────────────────────────────────────────────
def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    if 'user_id' in session:
        return query_db(
            'SELECT id, username, email, created_at FROM users WHERE id = %s',
            (session['user_id'],), one=True
        )
    return None


@app.context_processor
def inject_user():
    return dict(current_user=get_current_user())


# ─── Cloud Type Detection ────────────────────────────────────────────
def detect_cloud_type(url):
    if not url:
        return None
    url_lower = url.lower()
    if 'quark.cn' in url_lower or 'pan.quark' in url_lower:
        return 'quark'
    elif 'baidu.com' in url_lower or 'pan.baidu' in url_lower:
        return 'baidu'
    elif 'alipan.com' in url_lower or 'aliyundrive.com' in url_lower:
        return 'aliyun'
    elif '123pan.com' in url_lower or '123云盘' in url_lower:
        return '123pan'
    elif 'xunlei.com' in url_lower or 'pan.xunlei' in url_lower:
        return 'xunlei'
    elif 'guangyapan.com' in url_lower:
        return 'guangya'
    elif '115.com' in url_lower:
        return '115pan'
    elif 'lanzou' in url_lower:
        return 'lanzou'
    elif 'weiyun.com' in url_lower or '微云' in url_lower:
        return 'weiyun'
    elif 'ctfile.com' in url_lower or '城通' in url_lower:
        return 'ctfile'
    elif 'mega.nz' in url_lower or 'mega.co' in url_lower:
        return 'mega'
    elif 'drive.google.com' in url_lower or 'docs.google.com' in url_lower:
        return 'gdrive'
    elif 'dropbox.com' in url_lower:
        return 'dropbox'
    elif 'onedrive.live.com' in url_lower or '1drv.ms' in url_lower:
        return 'onedrive'
    elif 'pcloud.com' in url_lower:
        return 'pcloud'
    elif 'mediafire.com' in url_lower:
        return 'mediafire'
    elif 'wetransfer.com' in url_lower:
        return 'wetransfer'
    elif 'box.com' in url_lower:
        return 'box'
    else:
        return 'other'

CLOUD_NAMES = {
    'quark': '夸克网盘', 'baidu': '百度网盘', 'aliyun': '阿里云盘',
    '123pan': '123云盘', 'xunlei': '迅雷网盘', 'lanzou': '蓝奏云',
    'guangya': '光鸭网盘', '115pan': '115云盘', 'weiyun': '微云',
    'ctfile': '城通网盘', 'mega': 'Mega', 'gdrive': 'Google Drive',
    'dropbox': 'Dropbox', 'onedrive': 'OneDrive', 'pcloud': 'pCloud',
    'mediafire': 'MediaFire', 'wetransfer': 'WeTransfer', 'box': 'Box',
    'other': '其他网盘',
}


# ─── Routes ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    search = request.args.get('q', '').strip()
    category = request.args.get('cat', '').strip()

    sql = '''SELECT p.*, u.username as seller_name
             FROM products p
             LEFT JOIN users u ON p.user_id = u.id
             WHERE p.is_active = 1'''
    params = []

    if search:
        sql += ' AND (p.name LIKE %s OR p.description LIKE %s)'
        params.extend([f'%{search}%', f'%{search}%'])

    if category and category != 'all':
        sql += ' AND p.category = %s'
        params.append(category)

    sql += ' ORDER BY p.created_at DESC'
    products = query_db(sql, params)

    categories = query_db(
        'SELECT DISTINCT category FROM products WHERE is_active = 1 AND category IS NOT NULL ORDER BY category'
    )
    categories = [c['category'] for c in categories if c['category']]

    return render_template(
        'index.html',
        products=products,
        categories=categories,
        current_search=search,
        current_category=category,
    )


@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = query_db(
        '''SELECT p.*, u.username as seller_name
           FROM products p
           LEFT JOIN users u ON p.user_id = u.id
           WHERE p.id = %s AND p.is_active = 1''',
        (product_id,), one=True
    )
    if not product:
        flash('商品不存在', 'error')
        return redirect(url_for('index'))

    reviews = query_db(
        '''SELECT r.*, u.username
           FROM reviews r
           JOIN users u ON r.user_id = u.id
           WHERE r.product_id = %s
           ORDER BY r.created_at DESC''',
        (product_id,)
    )

    return render_template('product.html', product=product, reviews=reviews)


@app.route('/product/<int:product_id>/review', methods=['POST'])
@login_required
def add_review(product_id):
    rating = request.form.get('rating', 5, type=int)
    content = request.form.get('content', '').strip()

    if not content:
        flash('请输入评价内容', 'error')
        return redirect(url_for('product_detail', product_id=product_id))

    if rating < 1 or rating > 5:
        rating = 5

    modify_db(
        'INSERT INTO reviews (product_id, user_id, rating, content) VALUES (%s, %s, %s, %s)',
        (product_id, session['user_id'], rating, content)
    )

    flash('评价提交成功！', 'success')
    return redirect(url_for('product_detail', product_id=product_id))


# ─── Static Pages (bilingual) ───────────────────────────────────────

@app.route('/about.html')
def about_page():
    return render_template('about.html')

@app.route('/privacy.html')
def privacy_page():
    return render_template('privacy.html')


# ─── Auth Routes ──────────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        errors = []
        if len(username) < 3 or len(username) > 50:
            errors.append('用户名长度需在3-50个字符之间')
        if '@' not in email or '.' not in email:
            errors.append('请输入有效的邮箱地址')
        if len(password) < 6:
            errors.append('密码至少需要6个字符')
        if password != confirm:
            errors.append('两次输入的密码不一致')

        if not errors:
            existing = query_db(
                'SELECT id FROM users WHERE username = %s OR email = %s',
                (username, email), one=True
            )
            if existing:
                errors.append('用户名或邮箱已被注册')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('register.html', username=username, email=email)

        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
        user_id = modify_db(
            'INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)',
            (username, email, password_hash)
        )

        session.permanent = True
        session['user_id'] = user_id
        session['username'] = username
        flash('注册成功，欢迎！你现在可以发布自己的资源了', 'success')

        next_url = request.args.get('next', url_for('index'))
        return redirect(next_url)

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = query_db(
            'SELECT id, username, password_hash FROM users WHERE username = %s OR email = %s',
            (username, username), one=True
        )

        if user and bcrypt.check_password_hash(user['password_hash'], password):
            session.permanent = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash('登录成功', 'success')
            next_url = request.args.get('next', url_for('index'))
            return redirect(next_url)
        else:
            flash('用户名或密码错误', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录', 'info')
    return redirect(url_for('index'))


# ─── Dashboard ────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    products = query_db(
        'SELECT * FROM products WHERE user_id = %s ORDER BY created_at DESC',
        (user_id,)
    )
    stats = {
        'my_products': len(products),
        'my_active': sum(1 for p in products if p['is_active']),
    }
    categories = query_db(
        'SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category'
    )
    categories = [c['category'] for c in categories if c['category']]
    return render_template('admin.html', products=products, categories=categories, stats=stats)


@app.route('/dashboard/save', methods=['POST'])
@login_required
def save_product():
    pid = request.form.get('id', '').strip()
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    category = request.form.get('category', '').strip() or None
    image_url = request.form.get('image_url', '').strip() or None
    thumb_url = request.form.get('thumb_url', '').strip() or None
    quark_link = request.form.get('quark_link', '').strip()
    is_active = 1 if request.form.get('is_active') else 0
    contact_tg = request.form.get('contact_tg', '').strip() or None
    cloud_type = detect_cloud_type(quark_link)
    user_id = session['user_id']

    if not name or not quark_link:
        flash('名称和网盘链接必填', 'error')
        return redirect(url_for('dashboard'))

    if pid:
        existing = query_db(
            'SELECT id FROM products WHERE id = %s AND user_id = %s',
            (pid, user_id), one=True
        )
        if not existing:
            flash('无权编辑此商品', 'error')
            return redirect(url_for('dashboard'))

        modify_db(
            "UPDATE products SET name=%s, description=%s, category=%s, "
            "image_url=%s, thumb_url=%s, quark_link=%s, cloud_type=%s, contact_tg=%s, is_active=%s WHERE id=%s AND user_id=%s",
            (name, description, category, image_url, thumb_url, quark_link, cloud_type, contact_tg, is_active, pid, user_id)
        )
        flash(f'[{name}] 已更新', 'success')
    else:
        modify_db(
            "INSERT INTO products (name, description, category, image_url, thumb_url, quark_link, cloud_type, contact_tg, is_active, user_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (name, description, category, image_url, thumb_url, quark_link, cloud_type, contact_tg, is_active, user_id)
        )
        flash(f'[{name}] 已发布', 'success')

    return redirect(url_for('dashboard'))


@app.route('/dashboard/toggle/<int:product_id>', methods=['POST'])
@login_required
def toggle_product(product_id):
    user_id = session['user_id']
    product = query_db(
        'SELECT id, name, is_active FROM products WHERE id = %s AND user_id = %s',
        (product_id, user_id), one=True
    )
    if product:
        new_status = 0 if product['is_active'] else 1
        modify_db('UPDATE products SET is_active = %s WHERE id = %s AND user_id = %s',
                   (new_status, product_id, user_id))
        status_text = '上架' if new_status else '下架'
        flash(f'[{product["name"]}] 已{status_text}', 'success')
    else:
        flash('商品不存在或无权操作', 'error')
    return redirect(url_for('dashboard'))


@app.route('/dashboard/delete/<int:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    user_id = session['user_id']
    product = query_db(
        'SELECT name FROM products WHERE id = %s AND user_id = %s',
        (product_id, user_id), one=True
    )
    if product:
        try:
            # 先删除关联的订单和评论，再删商品
            modify_db('DELETE FROM orders WHERE product_id = %s', (product_id,))
            modify_db('DELETE FROM reviews WHERE product_id = %s', (product_id,))
            modify_db('DELETE FROM products WHERE id = %s AND user_id = %s', (product_id, user_id))
            flash(f'[{product["name"]}] 已删除', 'success')
        except Exception as e:
            modify_db('UPDATE products SET is_active = 0 WHERE id = %s AND user_id = %s', (product_id, user_id))
            flash(f'[{product["name"]}] 删除失败，已下架', 'error')
    else:
        flash('商品不存在或无权删除', 'error')
    return redirect(url_for('dashboard'))


@app.route('/dashboard/upload', methods=['POST'])
@login_required
def upload_image():
    if 'file' not in request.files:
        return jsonify({'error': '未选择文件'}), 400
    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': '未选择文件'}), 400

    allowed = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in allowed:
        return jsonify({'error': '不支持的格式'}), 400

    save_dir = os.path.join(app.root_path, 'images', 'products')
    os.makedirs(save_dir, exist_ok=True)

    filename = f"product_{int(time.time())}_{secrets.token_hex(4)}{ext}"
    filepath = os.path.join(save_dir, filename)
    f.save(filepath)

    url = f'/images/products/{filename}'
    return jsonify({'url': url, 'filename': filename})


# ─── Legacy admin redirect ───────────────────────────────────────────

@app.route('/violet27chen')
def admin_redirect():
    return redirect(url_for('dashboard'))


# ─── Error Handlers ───────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template('base.html', error_code=404, error_msg='页面未找到'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('base.html', error_code=500, error_msg='服务器错误'), 500


# ─── Run ──────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)

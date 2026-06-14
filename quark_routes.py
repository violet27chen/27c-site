#!/usr/bin/env python3
"""
Quark download proxy routes for 27c.site
"""

import os
import time
import secrets
import hashlib
import logging
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlencode

import pymysql
import pymysql.cursors
import requests
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    session, flash, jsonify, g, current_app
)

from quark_api import QuarkAPI, QuarkAPIError, calculate_price, _format_size

logger = logging.getLogger(__name__)

quark_bp = Blueprint('quark', __name__, url_prefix='/quark')

# ─── Quark Config ──────────────────────────────────────────────────
QUARK_COOKIE_FILE = '/var/www/27c.site/quark_cookie.txt'
QUARK_COS_DIR = '/mnt/cos/quark-downloads'
QUARK_FILE_EXPIRE_HOURS = 24  # 文件保留24小时

# EZF 配置（复用现有）
EZF_PID = '3336'
EZF_KEY = 'TzX6eCfzDtzLXCylN5K9RNcXn7CaVnA0'
EZF_SUBMIT_URL = 'https://www.ezfpy.cn/submit.php'
EZF_NOTIFY_URL = 'https://27c.site/quark/pay/notify'
EZF_RETURN_URL = 'https://27c.site/quark/pay/success'


# ─── Database Helpers ───────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = pymysql.connect(
            host='127.0.0.1',
            user='shopuser',
            password='ShopPass2026!',
            database='software_shop',
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
        )
    return g.db


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


# ─── Auth Helper ────────────────────────────────────────────────────
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('请先登录', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated


# ─── Cookie Management ─────────────────────────────────────────────
def get_quark_cookie():
    """读取夸克 Cookie"""
    if os.path.exists(QUARK_COOKIE_FILE):
        with open(QUARK_COOKIE_FILE, 'r') as f:
            return f.read().strip()
    return os.environ.get('QUARK_COOKIE', '')


def save_quark_cookie(cookie: str):
    """保存夸克 Cookie"""
    os.makedirs(os.path.dirname(QUARK_COOKIE_FILE), exist_ok=True)
    with open(QUARK_COOKIE_FILE, 'w') as f:
        f.write(cookie)


# ─── EZFpy Helpers ──────────────────────────────────────────────────
def ezf_sign(params):
    filtered = {
        k: v for k, v in params.items()
        if v is not None and v != '' and k not in ('sign', 'sign_type')
    }
    sign_str = '&'.join(f'{k}={v}' for k, v in sorted(filtered.items()))
    sign_str += EZF_KEY
    return hashlib.md5(sign_str.encode('utf-8')).hexdigest()


def ezf_verify(params):
    sign = params.get('sign', '')
    expected = ezf_sign(params)
    return sign == expected


def generate_order_no():
    timestamp = int(time.time() * 1000)
    random_part = secrets.token_hex(4).upper()
    return f'QK{timestamp}{random_part}'


# ─── Routes ─────────────────────────────────────────────────────────

@quark_bp.route('/')
def index():
    """夸克代下载首页"""
    return render_template('quark.html')



@quark_bp.route('/folder', methods=['POST'])
def parse_folder():
    """解析文件夹内容（JSON API）"""
    data = request.get_json()
    pwd_id = data.get('pwd_id', '')
    stoken = data.get('stoken', '')
    folder_fid = data.get('folder_fid', '')

    if not all([pwd_id, stoken, folder_fid]):
        return jsonify({'error': '参数不完整'}), 400

    cookie = get_quark_cookie()
    if not cookie:
        return jsonify({'error': '服务未配置Cookie'}), 500

    try:
        api = QuarkAPI(cookie)
        files = api.get_folder_files(pwd_id, stoken, folder_fid)

        result = []
        for f in files:
            is_dir = f.get("dir", False)
            result.append({
                "fid": f.get("fid", ""),
                "share_fid_token": f.get("share_fid_token", ""),
                "file_name": f.get("file_name", "未知文件"),
                "file_size": f.get("size", 0),
                "is_dir": is_dir,
                "format_size": _format_size(f.get("size", 0)),
                "price": calculate_price(f.get("size", 0)) if not is_dir else 0,
            })

        return jsonify({
            'success': True,
            'files': result,
            'total': len(result),
        })
    except QuarkAPIError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.exception('解析文件夹失败')
        return jsonify({'error': f'解析失败: {str(e)}'}), 500

@quark_bp.route('/parse', methods=['POST'])
def parse_link():
    """解析夸克分享链接（JSON API）"""
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'error': '请输入链接'}), 400

    if 'pan.quark.cn/s/' not in url:
        return jsonify({'error': '无效的夸克分享链接'}), 400

    cookie = get_quark_cookie()
    if not cookie:
        return jsonify({'error': '服务未配置Cookie，请联系管理员'}), 500

    try:
        api = QuarkAPI(cookie)
        result = api.parse_link(url)

        # 计算每个文件的价格
        for f in result['files']:
            f['price'] = calculate_price(f['file_size'])

        return jsonify({
            'success': True,
            'files': result['files'],
            'pwd_id': result['pwd_id'],
            'stoken': result['stoken'],
        })
    except QuarkAPIError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.exception('解析夸克链接失败')
        return jsonify({'error': f'解析失败: {str(e)}'}), 500


@quark_bp.route('/order', methods=['POST'])
def create_order():
    """创建下载订单"""
    data = request.get_json()
    pwd_id = data.get('pwd_id', '')
    stoken = data.get('stoken', '')
    fid = data.get('fid', '')
    file_name = data.get('file_name', '未知文件')
    file_size = data.get('file_size', 0)
    share_url = data.get('share_url', '')

    if not all([pwd_id, stoken, fid]):
        return jsonify({'error': '参数不完整'}), 400

    price = calculate_price(file_size)
    order_no = generate_order_no()

    # 创建订单
    modify_db(
        '''INSERT INTO quark_orders
           (order_no, user_id, share_url, pwd_id, stoken, fid, file_name, file_size, price, expires_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        (order_no, 0, share_url, pwd_id, stoken, fid,
         file_name, file_size, price,
         datetime.now() + timedelta(minutes=15))
    )

    # 构建支付参数
    params = {
        'pid': EZF_PID,
        'type': 'alipay',
        'out_trade_no': order_no,
        'notify_url': EZF_NOTIFY_URL,
        'return_url': f'{EZF_RETURN_URL}?order_no={order_no}',
        'name': f'夸克代下载 - {file_name[:30]}',
        'money': str(price),
    }
    params['sign'] = ezf_sign(params)
    params['sign_type'] = 'MD5'

    return jsonify({
        'success': True,
        'order_no': order_no,
        'pay_url': f'{EZF_SUBMIT_URL}?{urlencode(params)}',
    })


@quark_bp.route('/pay/notify', methods=['GET', 'POST'])
def payment_notify():
    """支付回调"""
    params = request.args.to_dict()
    if not params:
        params = request.form.to_dict()

    logger.info(f'Quark payment notify: {params}')

    if not ezf_verify(params):
        logger.warning(f'Sign verification failed: {params}')
        return 'fail', 400

    trade_status = params.get('trade_status', '')
    out_trade_no = params.get('out_trade_no', '')
    trade_no = params.get('trade_no', '')

    if trade_status == 'TRADE_SUCCESS':
        order = query_db(
            'SELECT id, status, created_at, expires_at FROM quark_orders WHERE order_no = %s',
            (out_trade_no,), one=True
        )

        if order and order['status'] == 'pending':
            # 检查是否过期
            expires = order.get('expires_at')
            if expires and datetime.now() > expires:
                modify_db("UPDATE quark_orders SET status = 'failed' WHERE id = %s", (order['id'],))
                logger.info(f'Order {out_trade_no} expired')
                return 'fail'

            # 标记已付款
            modify_db(
                "UPDATE quark_orders SET status = 'downloading', payment_no = %s, paid_at = NOW() WHERE id = %s",
                (trade_no, order['id'])
            )
            logger.info(f'Order {out_trade_no} marked as paid')

            # 异步开始下载
            threading.Thread(
                target=download_file_task,
                args=(order['id'],),
                daemon=True
            ).start()

    return 'success'


@quark_bp.route('/pay/success')
def pay_success():
    """支付成功页面"""
    order_no = request.args.get('order_no', '')
    if not order_no:
        return redirect(url_for('quark.index'))

    order = query_db(
        'SELECT * FROM quark_orders WHERE order_no = %s',
        (order_no,), one=True
    )

    if not order:
        flash('订单不存在', 'warning')
        return redirect(url_for('quark.index'))

    return render_template('quark_result.html', order=order)


@quark_bp.route('/status/<order_no>')
def order_status(order_no):
    """查询订单状态（JSON API）"""
    order = query_db(
        'SELECT * FROM quark_orders WHERE order_no = %s',
        (order_no,), one=True
    )

    if not order:
        return jsonify({'error': '订单不存在'}), 404

    return jsonify({
        'status': order['status'],
        'file_name': order['file_name'],
        'download_url': order.get('download_url'),
        'error_msg': order.get('error_msg'),
    })


# ─── Download Task ──────────────────────────────────────────────────

def download_file_task(order_id: int):
    """后台下载文件到 COS (独立于Flask上下文)"""
    import pymysql
    import pymysql.cursors

    def get_db_direct():
        return pymysql.connect(
            host='127.0.0.1', user='shopuser', password='ShopPass2026!',
            database='software_shop', charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )

    def query_direct(sql, args=None, one=False):
        db = get_db_direct()
        try:
            with db.cursor() as cursor:
                cursor.execute(sql, args)
                if one:
                    return cursor.fetchone()
                return cursor.fetchall()
        finally:
            db.close()

    def modify_direct(sql, args=None):
        db = get_db_direct()
        try:
            with db.cursor() as cursor:
                cursor.execute(sql, args)
            db.commit()
        finally:
            db.close()

    try:
        order = query_direct('SELECT * FROM quark_orders WHERE id = %s', (order_id,), one=True)
        if not order:
            return

        cookie = get_quark_cookie()
        api = QuarkAPI(cookie)

        # 获取下载地址
        download_info = api.get_download_url(order['fid'])
        download_url = download_info['download_url']

        # 准备 COS 目录
        cos_dir = os.path.join(QUARK_COS_DIR, order['order_no'])
        os.makedirs(cos_dir, exist_ok=True)
        cos_path = os.path.join(cos_dir, order['file_name'])

        # 下载文件
        logger.info(f'Downloading {order["file_name"]} from Quark...')
        resp = requests.get(download_url, stream=True, timeout=300,
                          headers={'user-agent': HEADERS_USER_AGENT})
        resp.raise_for_status()

        total = 0
        with open(cos_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)

        logger.info(f'Download complete: {order["file_name"]} ({total} bytes)')

        # 生成直链 URL
        download_link = f'https://27c.site/quark-files/{order["order_no"]}/{order["file_name"]}'

        # 更新订单
        modify_direct(
            """UPDATE quark_orders
               SET status = 'completed', cos_path = %s, download_url = %s
               WHERE id = %s""",
            (cos_path, download_link, order_id)
        )
        logger.info(f'Order {order["order_no"]} completed')

    except Exception as e:
        logger.exception(f'Download failed for order {order_id}')
        try:
            modify_direct(
                "UPDATE quark_orders SET status = 'failed', error_msg = %s WHERE id = %s",
                (str(e)[:500], order_id)
            )
        except:
            pass



HEADERS_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) quark-cloud-drive/3.14.2 Chrome/112.0.5615.165 Electron/24.1.3.8 Safari/537.36 Channel/pckk_other_ch"

import os
import json
import re
import subprocess
import psutil
import socket
import sys
import hashlib
import secrets
import time
import threading
import requests
import shutil
import zipfile
import signal
from datetime import datetime, timedelta
import urllib3
from flask import Flask, send_from_directory, request, jsonify, session, redirect, url_for, make_response
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, Float, Text, BigInteger, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

# ==========================================
# 🔄 إعداد نظام Keep-Alive المتقدم
# ==========================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# إعداد السجل (Logging)
logging_format = "[%(asctime)s] %(levelname)s: %(message)s"
# إذا كان هناك إعداد مسبق نستخدمه، أو نقوم بتهيئة أساسية
import logging
logging.basicConfig(
    level=logging.INFO,
    format=logging_format
)
logger = logging.getLogger(__name__)

class AdvancedKeepAlive:
    """نظام Keep-Alive متقدم مع حماية من التوقف المفاجئ وإعادة المحاولة"""
    
    def __init__(self, ping_interval=300):
        self.site_url = os.environ.get("RENDER_EXTERNAL_URL", "")
        self.is_running = True
        self.last_ping_time = datetime.now()
        self.ping_interval = ping_interval  # 5 دقائق افتراضياً (300 ثانية)
        self.max_retries = 3
        self.retry_delay = 5
        
    def format_url(self):
        """تنسيق رابط الموقع بشكل صحيح مع إزالة أي شرطات مائلة زائدة من النهاية"""
        if not self.site_url:
            return None
        url = self.site_url.strip()
        if not url.startswith("http"):
            url = f"https://{url}"
        return url.rstrip('/')
    
    def ping_server(self):
        """إرسال طلب Ping للموقع مع ربط المسار بشكل صحيح"""
        base_url = self.format_url()
        if not base_url:
            logger.warning("⚠️ لم يتم العثور على رابط الموقع (RENDER_EXTERNAL_URL)")
            return False
        
        target_url = f"{base_url}/api/ping"
        
        try:
            response = requests.get(
                target_url,
                headers={
                    "User-Agent": "EHAB-BRO-HOST-KEEP-ALIVE/1.0",
                    "X-Keep-Alive": "true"
                },
                timeout=15,
                verify=False
            )
            
            if response.status_code == 200:
                self.last_ping_time = datetime.now()
                logger.info(f"✅ Ping ناجح: {target_url}")
                return True
            else:
                logger.warning(f"⚠️ استجابة غير متوقعة: {response.status_code} من {target_url}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error("❌ انتهاء المهلة الزمنية (Timeout)")
            return False
        except requests.exceptions.ConnectionError:
            logger.error("❌ فشل الاتصال بالموقع")
            return False
        except Exception as e:
            logger.error(f"❌ خطأ في الـ Ping: {str(e)}")
            return False
    
    def ping_with_retry(self):
        """إرسال Ping مع إعادة محاولة عند الفشل"""
        for attempt in range(self.max_retries):
            if self.ping_server():
                return True
            
            if attempt < self.max_retries - 1:
                logger.info(f"🔄 إعادة محاولة {attempt + 1}/{self.max_retries - 1}...")
                time.sleep(self.retry_delay)
        
        logger.error("❌ فشلت جميع محاولات الـ Ping")
        return False
    
    def start(self):
        """بدء نظام Keep-Alive مع التنفيذ الفوري أول مرة"""
        logger.info("🚀 بدء نظام EHAB 𝗘𝗛𝗔𝗕 𝐇𝐎𝐒𝐓 Keep-Alive")
        formatted_url = self.format_url()
        logger.info(f"📍 رابط الموقع: {formatted_url if formatted_url else 'غير متوفر'}")
        logger.info(f"⏱️ فترة الـ Ping: {self.ping_interval} ثانية")
        
        # إرسال Ping فوري عند بدء التشغيل دون انتظار الفاصل الزمني
        if formatted_url:
            logger.info("📡 إرسال أول Ping فوري عند التشغيل...")
            self.ping_with_retry()
        
        while self.is_running:
            try:
                time.sleep(self.ping_interval)
                if not self.is_running:
                    break
                time_str = datetime.now().strftime("%H:%M:%S")
                logger.info(f"📡 إرسال Ping في {time_str}")
                self.ping_with_retry()
                
            except KeyboardInterrupt:
                logger.info("🛑 إيقاف نظام Keep-Alive...")
                self.is_running = False
            except Exception as e:
                logger.error(f"❌ خطأ غير متوقع: {str(e)}")
                time.sleep(10)
    
    def stop(self):
        """إيقاف نظام Keep-Alive"""
        self.is_running = False
        logger.info("✋ تم إيقاف نظام Keep-Alive")


def run_keep_alive_daemon():
    """تشغيل Keep-Alive كـ Daemon في الخلفية"""
    keep_alive = AdvancedKeepAlive()
    keep_alive.start()


# ==========================================
# 🌐 إعدادات التطبيق الأساسية (Flask & Paths)
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, "USERS")
os.makedirs(USERS_DIR, exist_ok=True)

# ============== Docker Support ==============
DOCKER_AVAILABLE = False
try:
    result_check = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
    DOCKER_AVAILABLE = result_check.returncode == 0
except:
    DOCKER_AVAILABLE = False

def generate_dockerfile(language, server_path):
    if language == 'python':
        req_path = os.path.join(server_path, "requirements.txt")
        if os.path.exists(req_path):
            with open(req_path, 'r', errors='ignore') as f:
                content = f.read().lower()
        return """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt* ./
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || echo "no requirements"
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD ["python", "-u", "main.py"]
"""
    elif language == 'nodejs':
        return """FROM node:18-slim
WORKDIR /app
COPY package*.json ./
RUN npm install 2>/dev/null || echo "no package.json"
COPY . .
ENV PORT=8080
EXPOSE 8080
CMD ["node", "index.js"]
"""
    return None

def get_container_name(folder):
    return ("elmodmen_" + folder).replace(" ", "_").lower()[:63]

def create_docker_container(folder, language, path, ram_limit=256, cpu_limit=0.5, storage_limit=100):
    if not DOCKER_AVAILABLE:
        return False, "Docker غير متاح على هذا السيرفر"
    container_name = get_container_name(folder)
    dockerfile_path = os.path.join(path, "Dockerfile")
    if not os.path.exists(dockerfile_path):
        content = generate_dockerfile(language, path)
        if content:
            with open(dockerfile_path, 'w') as f:
                f.write(content)
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
    image_name = ("elmodmen_" + folder + ":latest").lower()[:128]
    build_result = subprocess.run(
        ["docker", "build", "-t", image_name, "."],
        cwd=path, capture_output=True, text=True, timeout=300
    )
    if build_result.returncode != 0:
        return False, "فشل البناء:\n" + build_result.stderr[-500:]
    run_cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "--memory", str(ram_limit) + "m",
        "--cpus", str(cpu_limit),
        "--network", "none",
        "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:size=50m",
        "-v", path + ":/app",
        image_name
    ]
    run_result = subprocess.run(run_cmd, capture_output=True, text=True, timeout=30)
    if run_result.returncode != 0:
        return False, "فشل التشغيل:\n" + run_result.stderr[-500:]
    container_id = run_result.stdout.strip()
    return True, container_id

def stop_docker_container(folder):
    if not DOCKER_AVAILABLE:
        return
    subprocess.run(["docker", "stop", get_container_name(folder)], capture_output=True, timeout=15)

def remove_docker_container(folder):
    if not DOCKER_AVAILABLE:
        return
    cname = get_container_name(folder)
    iname = ("elmodmen_" + folder + ":latest").lower()[:128]
    subprocess.run(["docker", "stop", cname], capture_output=True, timeout=15)
    subprocess.run(["docker", "rm", "-f", cname], capture_output=True, timeout=10)
    subprocess.run(["docker", "rmi", "-f", iname], capture_output=True, timeout=10)

def get_docker_logs(folder, lines=500):
    if not DOCKER_AVAILABLE:
        return None
    cname = get_container_name(folder)
    result = subprocess.run(
        ["docker", "logs", "--tail", str(lines), cname],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        return (result.stdout + result.stderr)[-10000:]
    return None

def get_docker_stats(folder):
    if not DOCKER_AVAILABLE:
        return None
    cname = get_container_name(folder)
    result = subprocess.run(
        ["docker", "stats", "--no-stream", "--format",
         '{"cpu":"{{.CPUPerc}}","mem":"{{.MemUsage}}"}',
         cname],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            return json.loads(result.stdout.strip())
        except:
            pass
    return None

def is_docker_running(folder):
    if not DOCKER_AVAILABLE:
        return False
    cname = get_container_name(folder)
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", cname],
        capture_output=True, text=True, timeout=5
    )
    return result.stdout.strip() == "true"


app = Flask(__name__, static_folder=BASE_DIR)

# ============== تنظيف جلسة قاعدة البيانات بعد كل طلب ==============
@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

# ============== إعدادات الجلسة ==============
app.secret_key = "ELMODMEN_HOST_STABLE_SECRET_KEY_2026"
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ============== قاعدة البيانات ==============
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'db.sqlite')}"

# إصلاح رابط PostgreSQL (Render/Railway يستخدمون postgres:// القديم)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=10
)
db_session = scoped_session(sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False
))
Base = declarative_base()
Base.query = db_session.query_property()

# ============== تعريف الجداول ==============
class User(Base):
    __tablename__ = 'users'
    username = Column(String(50), primary_key=True)
    password = Column(String(128), nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    max_servers = Column(Integer, default=1)
    expiry_days = Column(Integer, default=365)
    last_login = Column(DateTime, nullable=True)
    telegram_id = Column(String(50), nullable=True)
    api_key = Column(String(128), nullable=True)
    is_unlimited = Column(Boolean, default=False)
    max_file_size_mb = Column(Integer, default=100)
    is_vip = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    ban_ip = Column(String(100), nullable=True)
    ban_reason = Column(String(200), nullable=True)
    is_pending = Column(Boolean, default=False)

class Server(Base):
    __tablename__ = 'servers'
    folder = Column(String(100), primary_key=True)
    owner = Column(String(50), nullable=False)
    name = Column(String(100), nullable=False)
    path = Column(String(500), nullable=False)
    type = Column(String(20), default="Python")
    language = Column(String(20), default="python")
    status = Column(String(20), default="Stopped")
    created_at = Column(DateTime, default=datetime.now)
    startup_file = Column(String(200), default="")
    pid = Column(Integer, nullable=True)
    port = Column(Integer, nullable=True)
    plan = Column(String(20), default="free")
    storage_limit = Column(Integer, default=100)
    ram_limit = Column(Integer, default=256)
    cpu_limit = Column(Float, default=0.5)
    start_time = Column(Float, nullable=True)

class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    is_read = Column(Boolean, default=False)

class Log(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.now)

# إضافة أعمدة الدعم والتحديث إذا لم تكن موجودة
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE servers ADD COLUMN language VARCHAR(20) DEFAULT 'python'"))
        conn.commit()
except Exception as e:
    pass

try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN is_pending BOOLEAN DEFAULT 0"))
        conn.commit()
except Exception as e:
    pass

Base.metadata.create_all(bind=engine)

# ============== بيانات المسؤول ==============
ADMIN_USERNAME = "ehab77"
ADMIN_PASSWORD_RAW = "ehab88#"

def create_default_admin():
    if not db_session.query(User).filter_by(username=ADMIN_USERNAME).first():
        admin = User(
            username=ADMIN_USERNAME,
            password=hashlib.sha256(ADMIN_PASSWORD_RAW.encode()).hexdigest(),
            is_admin=True,
            max_servers=999999,
            expiry_days=3650,
            is_unlimited=True,
            max_file_size_mb=500
        )
        db_session.add(admin)
        db_session.commit()
        print("✅ تم إنشاء المسؤول الافتراضي")

create_default_admin()

# ============== دوال مساعدة ==============
def get_user(username):
    return db_session.query(User).filter_by(username=username).first()

def get_server(folder):
    return db_session.query(Server).filter_by(folder=folder).first()

def get_user_servers(username):
    return db_session.query(Server).filter_by(owner=username).all()

def save_db():
    db_session.commit()

def add_notification(username, title, message):
    notif = Notification(username=username, title=title, message=message)
    db_session.add(notif)
    db_session.commit()

def get_user_notifications(username):
    return db_session.query(Notification).filter(
        (Notification.username == username) | (Notification.username == 'all')
    ).order_by(Notification.created_at.desc()).limit(50).all()

def mark_notification_read(notif_id):
    notif = db_session.query(Notification).filter_by(id=notif_id).first()
    if notif:
        notif.is_read = True
        db_session.commit()

# ============== المنافذ ==============
PORT_RANGE_START = 8100
PORT_RANGE_END = 9100

def get_assigned_port():
    used = set()
    for srv in db_session.query(Server).all():
        if srv.port:
            used.add(srv.port)
    for port in range(PORT_RANGE_START, PORT_RANGE_END):
        if port not in used:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.1)
                result = s.connect_ex(('127.0.0.1', port))
                s.close()
                if result != 0:
                    return port
            except:
                return port
    return PORT_RANGE_START

# ============== مراقبة العمليات ==============
def process_monitor():
    while True:
        try:
            for srv in db_session.query(Server).filter_by(status="Running"):
                if DOCKER_AVAILABLE:
                    if not is_docker_running(srv.folder):
                        restart_server(srv.folder)
                elif srv.pid:
                    try:
                        p = psutil.Process(srv.pid)
                        if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                            restart_server(srv.folder)
                    except psutil.NoSuchProcess:
                        restart_server(srv.folder)
                    except:
                        pass
        except:
            pass
        time.sleep(15)

def restart_server(folder):
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv:
        return
    if srv.pid:
        try:
            p = psutil.Process(srv.pid)
            if hasattr(os, 'killpg'):
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                except:
                    pass
            for child in p.children(recursive=True):
                child.kill()
            p.kill()
        except:
            pass
    srv.status = "Stopped"
    srv.pid = None
    db_session.commit()
    time.sleep(2)
    start_server_process(folder)

def start_server_docker(folder):
    """تشغيل المشروع داخل Docker Container معزول"""
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv:
        return False
    log_path = os.path.join(srv.path, "out.log")
    with open(log_path, "a", encoding='utf-8') as lf:
        lf.write(f"\n{'='*50}\n🐳 تشغيل Docker Container\n📁 {srv.name}\n🌐 اللغة: {srv.language}\n💾 RAM: {srv.ram_limit}MB | CPU: {srv.cpu_limit}\n{'='*50}\n\n")
    
    success, result = create_docker_container(
        folder=folder,
        language=srv.language,
        path=srv.path,
        ram_limit=srv.ram_limit,
        cpu_limit=srv.cpu_limit,
        storage_limit=srv.storage_limit
    )
    
    with open(log_path, "a", encoding='utf-8') as lf:
        if success:
            lf.write(f"✅ Container ID: {result}\n")
        else:
            lf.write(f"❌ فشل Docker: {result}\n")
    
    if success:
        srv.status = "Running"
        srv.pid = None
        srv.start_time = time.time()
        db_session.commit()
        return True
    return False

def start_server_process(folder):
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv:
        return False
    
    if DOCKER_AVAILABLE:
        return start_server_docker(folder)
    
    main_file = srv.startup_file
    if not main_file:
        lang = srv.language.lower()
        if lang == 'python':
            py_files = [f for f in os.listdir(srv.path) if f.endswith('.py') and f not in ['out.log', 'meta.json']]
            if py_files:
                main_file = py_files[0]
        elif lang == 'nodejs':
            if os.path.exists(os.path.join(srv.path, 'index.js')):
                main_file = 'index.js'
            elif os.path.exists(os.path.join(srv.path, 'app.js')):
                main_file = 'app.js'
        elif lang == 'java':
            jar_files = [f for f in os.listdir(srv.path) if f.endswith('.jar')]
            if jar_files:
                main_file = jar_files[0]
        elif lang == 'go':
            if os.path.exists(os.path.join(srv.path, 'main.go')):
                main_file = 'main.go'
        elif lang == 'php':
            if os.path.exists(os.path.join(srv.path, 'index.php')):
                main_file = 'index.php'
        if main_file:
            srv.startup_file = main_file
            db_session.commit()
        else:
            return False
    file_path = os.path.join(srv.path, main_file)
    if not os.path.exists(file_path):
        return False
    port = srv.port
    if not port:
        port = get_assigned_port()
        srv.port = port
        db_session.commit()
    log_path = os.path.join(srv.path, "out.log")
    log_file = open(log_path, "a", encoding='utf-8')
    log_file.write(f"\n{'='*50}\n🚀 بدء التشغيل - {datetime.now()}\n📁 {main_file}\n🔌 المنفذ: {port}\n🌐 اللغة: {srv.language}\n{'='*50}\n\n")
    log_file.flush()
    try:
        env = os.environ.copy()
        env["PORT"] = str(port)
        env["SERVER_PORT"] = str(port)
        lang = srv.language.lower()
        if lang == 'python':
            cmd = [sys.executable, "-u", main_file]
        elif lang == 'nodejs':
            cmd = ["node", main_file]
        elif lang == 'java':
            cmd = ["java", "-jar", main_file]
        elif lang == 'go':
            cmd = ["go", "run", main_file]
        elif lang == 'php':
            cmd = ["php", "-S", f"0.0.0.0:{port}", "-t", srv.path]
        else:
            cmd = [sys.executable, "-u", main_file]
        proc = subprocess.Popen(
            cmd,
            cwd=srv.path,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            preexec_fn=os.setsid if hasattr(os, 'setsid') else None
        )
        srv.status = "Running"
        srv.pid = proc.pid
        srv.start_time = time.time()
        db_session.commit()
        return True
    except Exception as e:
        log_file.write(f"\n❌ خطأ: {str(e)}\n")
        log_file.close()
        return False

# تشغيل خيط مراقبة السيرفرات
threading.Thread(target=process_monitor, daemon=True).start()

def get_current_user():
    if "username" in session:
        return db_session.query(User).filter_by(username=session["username"]).first()
    return None

def get_user_servers_dir(username):
    path = os.path.join(USERS_DIR, username, "SERVERS")
    os.makedirs(path, exist_ok=True)
    return path

def is_admin(username):
    if username == ADMIN_USERNAME:
        return True
    u = db_session.query(User).filter_by(username=username).first()
    return u.is_admin if u else False

def get_public_ip():
    try:
        return requests.get('https://api.ipify.org', timeout=3).text
    except:
        try:
            return requests.get('https://icanhazip.com', timeout=3).text.strip()
        except:
            return "127.0.0.1"

# ============== دوال API Key ==============
def generate_api_key():
    return secrets.token_urlsafe(32)

def get_user_by_api_key(api_key):
    user = db_session.query(User).filter_by(api_key=api_key).first()
    if user:
        return user.username, user
    return None, None

# ============== مسارات العرض والواجهة ==============
@app.route('/')
def home():
    if 'username' not in session:
        return redirect('/login')
    user = get_current_user()
    if user and user.is_admin:
        return redirect('/admin')
    return redirect('/dashboard')

@app.route('/login')
def login_page():
    if 'username' in session:
        return redirect('/')
    return send_from_directory(BASE_DIR, 'login.html')

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect('/login')
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/admin')
def admin_panel():
    if 'username' not in session or not is_admin(session['username']):
        return redirect('/login')
    return send_from_directory(BASE_DIR, 'admin_panel.html')

# ============== API المصادقة ==============
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"success": False, "message": "جميع الحقول مطلوبة"})
    if len(username) < 3:
        return jsonify({"success": False, "message": "اسم المستخدم 3 أحرف على الأقل"})
    if len(password) < 4:
        return jsonify({"success": False, "message": "كلمة المرور 4 أحرف على الأقل"})
    if db_session.query(User).filter_by(username=username).first():
        return jsonify({"success": False, "message": "اسم المستخدم موجود"})
    if username == ADMIN_USERNAME:
        return jsonify({"success": False, "message": "لا يمكن استخدام هذا الاسم"})
    
    new_user = User(
        username=username,
        password=hashlib.sha256(password.encode()).hexdigest(),
        is_admin=False,
        max_servers=1,
        expiry_days=365,
        max_file_size_mb=100,
        is_pending=True
    )
    db_session.add(new_user)
    try:
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        return jsonify({"success": False, "message": "خطأ في إنشاء الحساب، حاول مرة أخرى"})
    
    user_dir = os.path.join(USERS_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    os.makedirs(os.path.join(user_dir, "SERVERS"), exist_ok=True)
    
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'غير معروف').split(',')[0].strip()
    add_notification(ADMIN_USERNAME, "⏳ طلب حساب جديد", f"طلب تسجيل جديد ينتظر موافقتك\n👤 الاسم: {username}\n🌐 IP: {client_ip}\n\nاذهب إلى لوحة الأدمن > الحسابات المعلقة للموافقة أو الرفض")
    
    return jsonify({"success": True, "message": "تم إرسال طلب إنشاء الحساب! سيتم مراجعته من قِبل المسؤول وستُشعر بالنتيجة قريباً.", "pending": True})

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD_RAW:
        session.clear()
        session['username'] = username
        session.permanent = True
        return jsonify({"success": True, "redirect": "/admin", "is_admin": True})
    
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
    banned_by_ip = db_session.query(User).filter_by(ban_ip=client_ip, is_banned=True).first() if client_ip else None
    if banned_by_ip:
        return jsonify({"success": False, "message": "تم حظر هذا الجهاز من الوصول إلى المنصة"})
    
    db_session.expire_all()
    user = db_session.query(User).filter_by(username=username).first()
    if not user:
        return jsonify({"success": False, "message": "المستخدم غير موجود"})
    if user.password != hashlib.sha256(password.encode()).hexdigest():
        return jsonify({"success": False, "message": "كلمة المرور غير صحيحة"})
    if user.is_pending:
        return jsonify({"success": False, "message": "⏳ حسابك لا يزال قيد المراجعة. سيتم التواصل معك بعد موافقة المسؤول."})
    
    session.clear()
    session['username'] = username
    session.permanent = True
    user.last_login = datetime.now()
    try:
        db_session.commit()
    except Exception:
        db_session.rollback()
    return jsonify({"success": True, "redirect": "/dashboard", "is_admin": False})

@app.route('/api/logout', methods=['GET', 'POST'])
def api_logout():
    session.clear()
    response = make_response(jsonify({"success": True}))
    response.set_cookie('session', '', expires=0)
    return response

@app.route('/api/current_user')
def api_current_user():
    if "username" in session:
        u = db_session.query(User).filter_by(username=session["username"]).first()
        if u:
            return jsonify({
                "success": True,
                "username": session["username"],
                "is_admin": u.is_admin or session["username"] == ADMIN_USERNAME,
                "is_unlimited": u.is_unlimited,
                "max_file_size_mb": u.max_file_size_mb
            })
    return jsonify({"success": False})

@app.route('/api/create_api_key', methods=['POST'])
def create_api_key():
    if 'username' not in session:
        return jsonify({"success": False, "message": "غير مصرح"}), 401
    username = session['username']
    user = db_session.query(User).filter_by(username=username).first()
    new_key = generate_api_key()
    user.api_key = new_key
    db_session.commit()
    return jsonify({"success": True, "api_key": new_key})

@app.route('/api/pending_users', methods=['GET'])
def get_pending_users():
    if 'username' not in session or session['username'] != ADMIN_USERNAME:
        return jsonify({"success": False}), 403
    pending = db_session.query(User).filter_by(is_pending=True).all()
    return jsonify({"success": True, "users": [{"username": u.username, "created_at": str(u.created_at)} for u in pending]})

@app.route('/api/approve_user', methods=['POST'])
def approve_user():
    if 'username' not in session or session['username'] != ADMIN_USERNAME:
        return jsonify({"success": False}), 403
    data = request.get_json()
    username = data.get("username", "").strip()
    user = db_session.query(User).filter_by(username=username).first()
    if not user:
        return jsonify({"success": False, "message": "المستخدم غير موجود"})
    user.is_pending = False
    db_session.commit()
    add_notification(username, "✅ تم قبول حسابك", "مرحباً! تمت الموافقة على حسابك في 𝙴𝙻𝙼𝙾𝙳𝙼𝙴𝙽 𝙷𝙾𝚂𝚃. يمكنك الآن تسجيل الدخول.")
    return jsonify({"success": True, "message": f"تم قبول {username}"})

@app.route('/api/reject_user', methods=['POST'])
def reject_user():
    if 'username' not in session or session['username'] != ADMIN_USERNAME:
        return jsonify({"success": False}), 403
    data = request.get_json()
    username = data.get("username", "").strip()
    reason = data.get("reason", "رُفض الطلب من قِبل الإدارة")
    user = db_session.query(User).filter_by(username=username).first()
    if not user:
        return jsonify({"success": False, "message": "المستخدم غير موجود"})
    db_session.delete(user)
    db_session.commit()
    return jsonify({"success": True, "message": f"تم رفض وحذف {username}"})

@app.route('/api/admin/generate_api_key', methods=['POST'])
def admin_generate_api_key():
    if 'username' not in session or session['username'] != ADMIN_USERNAME:
        return jsonify({"success": False}), 403
    user = db_session.query(User).filter_by(username=ADMIN_USERNAME).first()
    if not user:
        return jsonify({"success": False, "message": "المسؤول غير موجود في قاعدة البيانات"})
    new_key = generate_api_key()
    user.api_key = new_key
    db_session.commit()
    return jsonify({"success": True, "api_key": new_key})

@app.route('/api/link_telegram', methods=['POST'])
def link_telegram():
    if 'username' not in session:
        return jsonify({"success": False}), 401
    data = request.get_json()
    tg_id = str(data.get('telegram_id'))
    user = db_session.query(User).filter_by(username=session['username']).first()
    user.telegram_id = tg_id
    db_session.commit()
    return jsonify({"success": True})

# ============== API الإشعارات ==============
@app.route('/api/notifications', methods=['GET'])
def get_notifications():
    if 'username' not in session:
        return jsonify({"success": False}), 401
    username = session['username']
    notifs = get_user_notifications(username)
    return jsonify({
        "success": True,
        "notifications": [{
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "created_at": str(n.created_at),
            "is_read": n.is_read
        } for n in notifs]
    })

@app.route('/api/notifications/mark_read', methods=['POST'])
def mark_read():
    if 'username' not in session:
        return jsonify({"success": False}), 401
    data = request.get_json()
    notif_id = data.get('id')
    if notif_id:
        mark_notification_read(notif_id)
    return jsonify({"success": True})

# ============== API المسؤول ==============
@app.route('/api/admin/upgrade-user', methods=['POST'])
def admin_upgrade_user():
    if 'username' not in session or not is_admin(session['username']):
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    data = request.get_json()
    target_username = data.get('username', '').strip()
    if not target_username or target_username == ADMIN_USERNAME:
        return jsonify({"success": False, "message": "لا يمكن ترقية هذا المستخدم"})
    user = db_session.query(User).filter_by(username=target_username).first()
    if not user:
        return jsonify({"success": False, "message": "المستخدم غير موجود"})
    user.is_unlimited = True
    user.max_servers = 999999
    user.max_file_size_mb = 500
    db_session.commit()
    add_notification(target_username, "⭐ تمت ترقيتك", "لقد تمت ترقيتك إلى صلاحيات غير محدودة! يمكنك الآن إنشاء سيرفرات غير محدودة ورفع ملفات بحجم كبير.")
    add_notification(ADMIN_USERNAME, "⭐ ترقية مستخدم", f"تم ترقية المستخدم {target_username} إلى صلاحيات غير محدودة")
    return jsonify({"success": True, "message": f"تم ترقية {target_username} بنجاح"})

@app.route('/api/admin/broadcast', methods=['POST'])
def admin_broadcast():
    if 'username' not in session or not is_admin(session['username']):
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    data = request.get_json()
    title = data.get('title', '').strip()
    message = data.get('message', '').strip()
    if not title or not message:
        return jsonify({"success": False, "message": "العنوان والرسالة مطلوبان"})
    add_notification('all', f"📢 {title}", message)
    add_notification(ADMIN_USERNAME, "📢 إذاعة", f"تم إرسال إذاعة: {title}")
    return jsonify({"success": True, "message": "تم إرسال الإذاعة لجميع المستخدمين"})

@app.route('/api/admin/users')
def admin_users():
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({"success": False}), 403
    users_list = []
    for u in db_session.query(User).all():
        users_list.append({
            "username": u.username,
            "is_admin": u.is_admin,
            "created_at": str(u.created_at) if u.created_at else None,
            "last_login": str(u.last_login) if u.last_login else None,
            "max_servers": u.max_servers,
            "expiry_days": u.expiry_days,
            "telegram_id": u.telegram_id,
            "api_key": u.api_key,
            "is_unlimited": u.is_unlimited
        })
    return jsonify({"success": True, "users": users_list})

@app.route('/api/admin/create-user', methods=['POST'])
def admin_create_user():
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({"success": False}), 403
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    max_servers = int(data.get("max_servers", 1))
    expiry_days = int(data.get("expiry_days", 365))
    if not username or not password:
        return jsonify({"success": False, "message": "جميع الحقول مطلوبة"})
    if db_session.query(User).filter_by(username=username).first():
        return jsonify({"success": False, "message": "المستخدم موجود"})
    new_user = User(
        username=username,
        password=hashlib.sha256(password.encode()).hexdigest(),
        is_admin=False,
        max_servers=max_servers,
        expiry_days=expiry_days,
        max_file_size_mb=100
    )
    db_session.add(new_user)
    db_session.commit()
    user_dir = os.path.join(USERS_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    os.makedirs(os.path.join(user_dir, "SERVERS"), exist_ok=True)
    add_notification(ADMIN_USERNAME, "👤 مستخدم جديد", f"تم إنشاء حساب جديد بواسطة المسؤول: {username}")
    return jsonify({"success": True, "message": "✅ تم إنشاء الحساب"})

@app.route('/api/admin/delete-user', methods=['POST'])
def admin_delete_user():
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({"success": False}), 403
    data = request.get_json()
    username = data.get("username", "").strip()
    if not username or username == ADMIN_USERNAME:
        return jsonify({"success": False, "message": "لا يمكن حذف هذا المستخدم"})
    user = db_session.query(User).filter_by(username=username).first()
    if user:
        servers = db_session.query(Server).filter_by(owner=username).all()
        for srv in servers:
            if srv.pid:
                try:
                    p = psutil.Process(srv.pid)
                    p.terminate()
                except:
                    pass
            if os.path.exists(srv.path):
                try:
                    shutil.rmtree(srv.path)
                except:
                    pass
            db_session.delete(srv)
        user_dir = os.path.join(USERS_DIR, username)
        if os.path.exists(user_dir):
            try:
                shutil.rmtree(user_dir)
            except:
                pass
        db_session.delete(user)
        db_session.commit()
        return jsonify({"success": True, "message": f"🗑️ تم حذف {username}"})
    return jsonify({"success": False, "message": "المستخدم غير موجود"})

# ============== API النظام ==============
@app.route('/api/system/metrics')
def get_metrics():
    return jsonify({
        "cpu": psutil.cpu_percent(),
        "memory": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage('/').percent
    })

@app.route('/api/ping', methods=['GET', 'POST'])
def ping():
    return jsonify({"status": "pong", "timestamp": str(datetime.now())})

# ============== السيرفرات ==============
@app.route('/api/servers')
def list_servers():
    if "username" not in session:
        return jsonify({"success": False}), 401
    user_servers = []
    total_disk_used = 0
    total_disk_limit = 0
    for srv in db_session.query(Server).filter_by(owner=session["username"]):
        disk_used = 0
        if os.path.exists(srv.path):
            for root, dirs, files in os.walk(srv.path):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.exists(fp):
                        disk_used += os.path.getsize(fp)
        disk_used_mb = disk_used / (1024 * 1024)
        storage_limit = srv.storage_limit
        total_disk_used += disk_used_mb
        total_disk_limit += storage_limit
        uptime_str = "0 ثانية"
        if srv.status == "Running" and srv.start_time:
            diff = time.time() - srv.start_time
            days = int(diff // 86400)
            hours = int((diff % 86400) // 3600)
            mins = int((diff % 3600) // 60)
            parts = []
            if days > 0: parts.append(f"{days} يوم")
            if hours > 0: parts.append(f"{hours} ساعة")
            if mins > 0: parts.append(f"{mins} دقيقة")
            uptime_str = " و ".join(parts) if parts else "أقل من دقيقة"
        user_servers.append({
            "folder": srv.folder,
            "title": srv.name,
            "subtitle": f"سيرفر {srv.type}",
            "startup_file": srv.startup_file,
            "status": srv.status,
            "uptime": uptime_str,
            "port": srv.port or "N/A",
            "plan": srv.plan,
            "language": srv.language,
            "storage_limit": storage_limit,
            "ram_limit": srv.ram_limit,
            "cpu_limit": srv.cpu_limit,
            "disk_used": round(disk_used_mb, 2)
        })
    user = db_session.query(User).filter_by(username=session["username"]).first()
    max_srv = user.max_servers if user else 1
    return jsonify({
        "success": True,
        "servers": user_servers,
        "stats": {
            "used": len(user_servers),
            "total": max_srv,
            "expiry": user.expiry_days if user else 365,
            "disk_used": round(total_disk_used, 2),
            "disk_total": total_disk_limit
        }
    })

@app.route('/api/server/add', methods=['POST'])
def add_server():
    if "username" not in session:
        return jsonify({"success": False, "message": "غير مصرح"}), 401
    user = db_session.query(User).filter_by(username=session["username"]).first()
    if not user:
        return jsonify({"success": False, "message": "مستخدم غير موجود"})
    user_srv_count = db_session.query(Server).filter_by(owner=session["username"]).count()
    if user_srv_count >= user.max_servers:
        return jsonify({"success": False, "message": "لقد وصلت للحد الأقصى من السيرفرات"})
    data = request.get_json()
    name = data.get("name", "My Server").strip()
    plan_id = data.get("plan", "free")
    storage_limit = int(data.get("storage", 100))
    ram_limit = int(data.get("ram", 256))
    cpu_limit = float(data.get("cpu", 0.5))
    language = data.get("language", "python").strip().lower()
    if not name:
        name = "Server_" + secrets.token_hex(2)
    folder = f"{session['username']}_{re.sub(r'[^a-zA-Z0-9]', '', name)}_{int(time.time())}"
    path = os.path.join(get_user_servers_dir(session["username"]), folder)
    os.makedirs(path, exist_ok=True)
    assigned_port = get_assigned_port()
    new_server = Server(
        folder=folder,
        owner=session["username"],
        name=name,
        path=path,
        status="Stopped",
        port=assigned_port,
        plan=plan_id,
        storage_limit=storage_limit,
        ram_limit=ram_limit,
        cpu_limit=cpu_limit,
        language=language
    )
    db_session.add(new_server)
    db_session.commit()
    return jsonify({"success": True, "message": f"✅ تم إنشاء الخادم {name}"})

@app.route('/api/server/action/<folder>/<action>', methods=['POST'])
def server_action(folder, action):
    if "username" not in session:
        return jsonify({"success": False}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"success": False, "message": "غير مصرح"})
    if action == "start":
        if srv.status == "Running":
            return jsonify({"success": False, "message": "الخادم يعمل بالفعل"})
        if start_server_process(folder):
            return jsonify({"success": True, "message": "✅ تم التشغيل"})
        else:
            return jsonify({"success": False, "message": "فشل التشغيل"})
    elif action == "stop":
        if srv.pid:
            try:
                p = psutil.Process(srv.pid)
                if hasattr(os, 'killpg'):
                    try:
                        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                    except:
                        pass
                for child in p.children(recursive=True):
                    child.kill()
                p.kill()
            except:
                pass
        srv.status = "Stopped"
        srv.pid = None
        db_session.commit()
        return jsonify({"success": True, "message": "🛑 تم الإيقاف"})
    elif action == "restart":
        restart_server(folder)
        return jsonify({"success": True, "message": "✅ تم إعادة التشغيل"})
    elif action == "delete":
        remove_docker_container(folder)
        if srv.pid:
            try:
                p = psutil.Process(srv.pid)
                if hasattr(os, 'killpg'):
                    try:
                        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                    except:
                        pass
                for child in p.children(recursive=True):
                    child.kill()
                p.kill()
            except:
                pass
        if os.path.exists(srv.path):
            try:
                shutil.rmtree(srv.path)
            except:
                try:
                    subprocess.run(["rm", "-rf", srv.path], timeout=5)
                except:
                    pass
        db_session.delete(srv)
        db_session.commit()
        return jsonify({"success": True, "message": "🗑️ تم الحذف"})
    return jsonify({"success": False})

@app.route('/api/server/stats/<folder>')
def get_server_stats(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"success": False})
    status = srv.status
    logs = "لا توجد مخرجات بعد"
    docker_logs = get_docker_logs(srv.folder) if DOCKER_AVAILABLE else None
    if docker_logs:
        logs = docker_logs
    else:
        log_path = os.path.join(srv.path, "out.log")
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.read().split('\n')
                    logs = '\n'.join(lines[-500:])
            except:
                pass
    mem_info = "0 MB"
    if srv.pid and status == "Running":
        try:
            p = psutil.Process(srv.pid)
            mem_mb = p.memory_info().rss / (1024 * 1024)
            mem_info = f"{mem_mb:.1f} MB"
        except:
            pass
    uptime_str = "0 ثانية"
    if status == "Running" and srv.start_time:
        diff = time.time() - srv.start_time
        days = int(diff // 86400)
        hours = int((diff % 86400) // 3600)
        mins = int((diff % 3600) // 60)
        parts = []
        if days > 0: parts.append(f"{days} يوم")
        if hours > 0: parts.append(f"{hours} ساعة")
        if mins > 0: parts.append(f"{mins} دقيقة")
        uptime_str = " و ".join(parts) if parts else "أقل من دقيقة"
    return jsonify({
        "success": True,
        "status": status,
        "logs": logs,
        "mem": mem_info,
        "uptime": uptime_str,
        "port": srv.port or "--",
        "ip": get_public_ip()
    })

# ============== API الملفات ==============
@app.route('/api/files/list/<folder>')
def list_server_files(folder):
    if "username" not in session:
        return jsonify([]), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify([])
    path = srv.path
    files = []
    try:
        for f in os.listdir(path):
            if f in ['out.log', 'server.log', 'meta.json']:
                continue
            fpath = os.path.join(path, f)
            stat = os.stat(fpath)
            size_bytes = stat.st_size
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024*1024:
                size_str = f"{size_bytes/1024:.1f} KB"
            else:
                size_str = f"{size_bytes/(1024*1024):.1f} MB"
            files.append({"name": f, "size": size_str, "is_dir": os.path.isdir(fpath), "modified": datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')})
    except:
        pass
    return jsonify(sorted(files, key=lambda x: (not x['is_dir'], x['name'].lower())))

@app.route('/api/files/content/<folder>/<filename>')
def get_file_content(folder, filename):
    if "username" not in session:
        return jsonify({"content": ""}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"content": ""})
    if '..' in filename:
        return jsonify({"content": ""})
    fpath = os.path.join(srv.path, filename)
    if not os.path.exists(fpath) or os.path.isdir(fpath):
        return jsonify({"content": ""})
    try:
        with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
            return jsonify({"content": f.read()})
    except:
        return jsonify({"content": "[ملف ثنائي]"})

@app.route('/api/files/save/<folder>/<filename>', methods=['POST'])
def save_file_content(folder, filename):
    if "username" not in session:
        return jsonify({"success": False}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"success": False})
    if '..' in filename:
        return jsonify({"success": False, "message": "اسم غير صالح"})
    data = request.get_json()
    content = data.get("content", "")
    fpath = os.path.join(srv.path, filename)
    try:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"success": True, "message": "✅ تم الحفظ"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/files/create/<folder>', methods=['POST'])
def create_file(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"success": False})
    data = request.get_json()
    filename = data.get("filename", "").strip()
    content = data.get("content", "")
    if not filename or '..' in filename:
        return jsonify({"success": False, "message": "اسم غير صالح"})
    fpath = os.path.join(srv.path, filename)
    try:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"success": True, "message": f"✅ تم إنشاء {filename}"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/files/delete/<folder>', methods=['POST'])
def delete_files(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"success": False})
    data = request.get_json() or {}
    names = data.get("names", data.get("name", []))
    if isinstance(names, str):
        names = [names]
    if not names:
        return jsonify({"success": False, "message": "لم يتم تحديد ملفات"})
    deleted = 0
    for name in names:
        if not name or '..' in name:
            continue
        fpath = os.path.join(srv.path, name)
        try:
            if os.path.isdir(fpath):
                shutil.rmtree(fpath)
            elif os.path.exists(fpath):
                os.remove(fpath)
            deleted += 1
        except:
            pass
    if deleted > 0:
        return jsonify({"success": True, "message": f"🗑️ تم حذف {deleted} ملف"})
    else:
        return jsonify({"success": False, "message": "فشل الحذف"})

@app.route('/api/files/upload/<folder>', methods=['POST'])
def upload_files(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"success": False})
    user = get_user(session["username"])
    max_file_size_mb = user.max_file_size_mb if user else 100
    max_file_size_bytes = max_file_size_mb * 1024 * 1024
    
    if not os.path.exists(srv.path):
        os.makedirs(srv.path, exist_ok=True)
    files = request.files.getlist('files[]')
    if not files:
        return jsonify({"success": False, "message": "لا توجد ملفات"})
    uploaded = 0
    for f in files:
        try:
            if not f or not f.filename:
                continue
            if '..' in f.filename:
                continue
            f.seek(0, 2)
            size = f.tell()
            f.seek(0)
            if size > max_file_size_bytes:
                return jsonify({"success": False, "message": f"الملف {f.filename} أكبر من {max_file_size_mb} MB"})
            save_path = os.path.join(srv.path, f.filename)
            f.save(save_path)
            if f.filename.lower().endswith('.zip'):
                try:
                    with zipfile.ZipFile(save_path, 'r') as z:
                        z.extractall(srv.path)
                except:
                    pass
            uploaded += 1
        except:
            pass
    if uploaded > 0:
        return jsonify({"success": True, "message": f"✅ تم رفع {uploaded} ملف"})
    else:
        return jsonify({"success": False, "message": "فشل الرفع"})

@app.route('/api/files/unzip/<folder>/<filename>', methods=['POST'])
def unzip_file(folder, filename):
    if "username" not in session:
        return jsonify({"success": False}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"success": False})
    if '..' in filename or not filename.lower().endswith('.zip'):
        return jsonify({"success": False, "message": "ملف غير صالح"})
    fpath = os.path.join(srv.path, filename)
    if not os.path.exists(fpath):
        return jsonify({"success": False, "message": "الملف غير موجود"})
    try:
        with zipfile.ZipFile(fpath, 'r') as z:
            z.extractall(srv.path)
        return jsonify({"success": True, "message": "✅ تم فك الضغط"})
    except Exception as e:
        return jsonify({"success": False, "message": f"❌ فشل: {str(e)}"})

@app.route('/api/server/set-startup/<folder>', methods=['POST'])
def set_startup_file(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"success": False})
    data = request.get_json()
    filename = data.get("filename", "").strip()
    if not filename or '..' in filename:
        return jsonify({"success": False, "message": "اسم غير صالح"})
    file_path = os.path.join(srv.path, filename)
    if not os.path.exists(file_path):
        return jsonify({"success": False, "message": "الملف غير موجود"})
    srv.startup_file = filename
    db_session.commit()
    return jsonify({"success": True, "message": f"✅ تم تعيين {filename} كملف التشغيل"})

@app.route('/api/server/install/<folder>', methods=['POST'])
def install_requirements(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"success": False})
    req_file = os.path.join(srv.path, "requirements.txt")
    if os.path.exists(req_file):
        try:
            log_path = os.path.join(srv.path, "out.log")
            with open(log_path, "a", encoding='utf-8') as log_file:
                log_file.write(f"\n{'='*50}\n📦 بدء تثبيت المكتبات...\n{'='*50}\n")
            subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=srv.path,
                stdout=open(log_path, "a", encoding='utf-8'),
                stderr=subprocess.STDOUT
            )
            return jsonify({"success": True, "message": "📦 بدأ تثبيت المكتبات"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})
    return jsonify({"success": False, "message": "requirements.txt غير موجود"})

# ============== API للبوت ==============
@app.route('/api/bot/verify', methods=['POST'])
def bot_verify():
    data = request.get_json()
    api_key = data.get('api_key', '').strip()
    if not api_key:
        return jsonify({"success": False, "message": "API Key مطلوب"})
    username, user = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"})
    return jsonify({
        "success": True,
        "username": username,
        "is_admin": user.is_admin,
        "max_servers": user.max_servers,
        "expiry_days": user.expiry_days,
        "is_unlimited": user.is_unlimited
    })

@app.route('/api/bot/servers', methods=['GET'])
def bot_list_servers():
    api_key = request.args.get('api_key')
    if not api_key:
        return jsonify({"success": False, "message": "API Key مطلوب"}), 401
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    user_servers = []
    for srv in db_session.query(Server).filter_by(owner=username):
        uptime_str = "0 ثانية"
        if srv.status == "Running" and srv.start_time:
            diff = time.time() - srv.start_time
            days = int(diff // 86400)
            hours = int((diff % 86400) // 3600)
            mins = int((diff % 3600) // 60)
            parts = []
            if days > 0: parts.append(f"{days} يوم")
            if hours > 0: parts.append(f"{hours} ساعة")
            if mins > 0: parts.append(f"{mins} دقيقة")
            uptime_str = " و ".join(parts) if parts else "أقل من دقيقة"
        user_servers.append({
            "folder": srv.folder,
            "title": srv.name,
            "status": srv.status,
            "uptime": uptime_str,
            "port": srv.port or "N/A",
            "plan": srv.plan,
            "language": srv.language,
            "storage_limit": srv.storage_limit,
            "ram_limit": srv.ram_limit,
            "cpu_limit": srv.cpu_limit
        })
    return jsonify({"success": True, "servers": user_servers})

@app.route('/api/bot/server/action', methods=['POST'])
def bot_server_action():
    data = request.get_json()
    api_key = data.get('api_key')
    folder = data.get('folder')
    action = data.get('action')
    if not api_key or not folder or not action:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    if action == "start":
        if srv.status == "Running":
            return jsonify({"success": False, "message": "السيرفر يعمل بالفعل"})
        if start_server_process(folder):
            return jsonify({"success": True, "message": "✅ تم التشغيل"})
        else:
            return jsonify({"success": False, "message": "فشل التشغيل"})
    elif action == "stop":
        if srv.pid:
            try:
                p = psutil.Process(srv.pid)
                if hasattr(os, 'killpg'):
                    try:
                        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                    except:
                        pass
                for child in p.children(recursive=True):
                    child.kill()
                p.kill()
            except:
                pass
        srv.status = "Stopped"
        srv.pid = None
        db_session.commit()
        return jsonify({"success": True, "message": "🛑 تم الإيقاف"})
    elif action == "restart":
        restart_server(folder)
        return jsonify({"success": True, "message": "✅ تم إعادة التشغيل"})
    elif action == "delete":
        if srv.pid:
            try:
                p = psutil.Process(srv.pid)
                if hasattr(os, 'killpg'):
                    try:
                        os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                    except:
                        pass
                for child in p.children(recursive=True):
                    child.kill()
                p.kill()
            except:
                pass
        if os.path.exists(srv.path):
            try:
                shutil.rmtree(srv.path)
            except:
                try:
                    subprocess.run(["rm", "-rf", srv.path], timeout=5)
                except:
                    pass
        db_session.delete(srv)
        db_session.commit()
        return jsonify({"success": True, "message": "🗑️ تم الحذف"})
    else:
        return jsonify({"success": False, "message": "إجراء غير معروف"})

@app.route('/api/bot/console', methods=['GET'])
def bot_console():
    api_key = request.args.get('api_key')
    folder = request.args.get('folder')
    if not api_key or not folder:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    log_path = os.path.join(srv.path, "out.log")
    logs = "لا توجد مخرجات بعد"
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.read().split('\n')
                logs = '\n'.join(lines[-500:])
        except:
            pass
    return jsonify({"success": True, "logs": logs})

@app.route('/api/bot/files/list', methods=['GET'])
def bot_files_list():
    api_key = request.args.get('api_key')
    folder = request.args.get('folder')
    path = request.args.get('path', '')
    if not api_key or not folder:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    base_path = srv.path
    target_path = os.path.join(base_path, path) if path else base_path
    if '..' in target_path or not target_path.startswith(base_path):
        return jsonify({"success": False, "message": "مسار غير صالح"}), 400
    files = []
    try:
        for f in os.listdir(target_path):
            if f in ['out.log', 'server.log', 'meta.json']:
                continue
            fpath = os.path.join(target_path, f)
            stat = os.stat(fpath)
            size_bytes = stat.st_size
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024*1024:
                size_str = f"{size_bytes/1024:.1f} KB"
            else:
                size_str = f"{size_bytes/(1024*1024):.1f} MB"
            files.append({
                "name": f,
                "size": size_str,
                "is_dir": os.path.isdir(fpath),
                "path": os.path.join(path, f) if path else f
            })
    except:
        pass
    return jsonify({"success": True, "files": files, "current_path": path})

@app.route('/api/bot/files/content', methods=['GET'])
def bot_file_content():
    api_key = request.args.get('api_key')
    folder = request.args.get('folder')
    file_path = request.args.get('file_path')
    if not api_key or not folder or not file_path:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    full_path = os.path.join(srv.path, file_path)
    if '..' in full_path or not full_path.startswith(srv.path):
        return jsonify({"success": False, "message": "مسار غير صالح"}), 400
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return jsonify({"success": False, "message": "ملف غير موجود"}), 404
    try:
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return jsonify({"success": True, "content": content})
    except:
        return jsonify({"success": False, "message": "فشل قراءة الملف"}), 500

@app.route('/api/bot/files/save', methods=['POST'])
def bot_file_save():
    data = request.get_json()
    api_key = data.get('api_key')
    folder = data.get('folder')
    file_path = data.get('file_path')
    content = data.get('content', '')
    if not api_key or not folder or not file_path:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    full_path = os.path.join(srv.path, file_path)
    if '..' in full_path or not full_path.startswith(srv.path):
        return jsonify({"success": False, "message": "مسار غير صالح"}), 400
    try:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({"success": True, "message": "تم الحفظ"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/files/delete', methods=['POST'])
def bot_file_delete():
    data = request.get_json()
    api_key = data.get('api_key')
    folder = data.get('folder')
    file_path = data.get('file_path')
    if not api_key or not folder or not file_path:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    full_path = os.path.join(srv.path, file_path)
    if '..' in full_path or not full_path.startswith(srv.path):
        return jsonify({"success": False, "message": "مسار غير صالح"}), 400
    try:
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
        else:
            os.remove(full_path)
        return jsonify({"success": True, "message": "تم الحذف"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/files/upload', methods=['POST'])
def bot_file_upload():
    api_key = request.form.get('api_key')
    folder = request.form.get('folder')
    file_path = request.form.get('file_path', '')
    uploaded_file = request.files.get('file')
    if not api_key or not folder or not uploaded_file:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    username, user = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    max_file_size_mb = user.max_file_size_mb if user else 100
    max_file_size_bytes = max_file_size_mb * 1024 * 1024
    target_dir = os.path.join(srv.path, file_path) if file_path else srv.path
    if '..' in target_dir or not target_dir.startswith(srv.path):
        return jsonify({"success": False, "message": "مسار غير صالح"}), 400
    os.makedirs(target_dir, exist_ok=True)
    filename = uploaded_file.filename
    if '..' in filename:
        return jsonify({"success": False, "message": "اسم ملف غير صالح"}), 400
    full_path = os.path.join(target_dir, filename)
    uploaded_file.seek(0, 2)
    size = uploaded_file.tell()
    uploaded_file.seek(0)
    if size > max_file_size_bytes:
        return jsonify({"success": False, "message": f"الملف أكبر من {max_file_size_mb} MB"}), 400
    uploaded_file.save(full_path)
    return jsonify({"success": True, "message": f"تم رفع {filename}"})

@app.route('/api/bot/files/create_folder', methods=['POST'])
def bot_create_folder():
    data = request.get_json()
    api_key = data.get('api_key')
    folder = data.get('folder')
    folder_name = data.get('folder_name')
    current_path = data.get('current_path', '')
    if not api_key or not folder or not folder_name:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    target_dir = os.path.join(srv.path, current_path, folder_name)
    if '..' in target_dir or not target_dir.startswith(srv.path):
        return jsonify({"success": False, "message": "مسار غير صالح"}), 400
    os.makedirs(target_dir, exist_ok=True)
    return jsonify({"success": True, "message": f"تم إنشاء المجلد {folder_name}"})

@app.route('/api/bot/install', methods=['POST'])
def bot_install():
    data = request.get_json()
    api_key = data.get('api_key')
    folder = data.get('folder')
    if not api_key or not folder:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    req_file = os.path.join(srv.path, "requirements.txt")
    if not os.path.exists(req_file):
        return jsonify({"success": False, "message": "requirements.txt غير موجود"}), 404
    try:
        log_path = os.path.join(srv.path, "out.log")
        with open(log_path, "a", encoding='utf-8') as log_file:
            log_file.write(f"\n{'='*50}\n📦 بدء تثبيت المكتبات...\n{'='*50}\n")
        subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=srv.path,
            stdout=open(log_path, "a", encoding='utf-8'),
            stderr=subprocess.STDOUT
        )
        return jsonify({"success": True, "message": "بدأ تثبيت المكتبات"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/bot/set_startup', methods=['POST'])
def bot_set_startup():
    data = request.get_json()
    api_key = data.get('api_key')
    folder = data.get('folder')
    filename = data.get('filename')
    if not api_key or not folder or not filename:
        return jsonify({"success": False, "message": "بيانات ناقصة"}), 400
    username, _ = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != username:
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    file_path = os.path.join(srv.path, filename)
    if not os.path.exists(file_path):
        return jsonify({"success": False, "message": "الملف غير موجود"}), 404
    srv.startup_file = filename
    db_session.commit()
    return jsonify({"success": True, "message": f"تم تعيين {filename} كملف التشغيل"})

@app.route('/api/bot/create_server', methods=['POST'])
def bot_create_server():
    data = request.get_json()
    api_key = data.get('api_key')
    name = data.get('name', 'خادمي').strip()
    plan_id = data.get('plan', 'free')
    storage_limit = int(data.get('storage', 100))
    ram_limit = int(data.get('ram', 256))
    cpu_limit = float(data.get('cpu', 0.5))
    language = data.get('language', 'python').strip().lower()
    if not api_key:
        return jsonify({"success": False, "message": "API Key مطلوب"}), 400
    username, user = get_user_by_api_key(api_key)
    if not username:
        return jsonify({"success": False, "message": "API Key غير صالح"}), 401
    user_srv_count = db_session.query(Server).filter_by(owner=username).count()
    if user_srv_count >= user.max_servers:
        return jsonify({"success": False, "message": f"لقد وصلت للحد الأقصى ({user.max_servers})"})
    folder = f"{username}_{re.sub(r'[^a-zA-Z0-9]', '', name)}_{int(time.time())}"
    path = os.path.join(get_user_servers_dir(username), folder)
    os.makedirs(path, exist_ok=True)
    assigned_port = get_assigned_port()
    new_server = Server(
        folder=folder,
        owner=username,
        name=name,
        path=path,
        status="Stopped",
        port=assigned_port,
        plan=plan_id,
        storage_limit=storage_limit,
        ram_limit=ram_limit,
        cpu_limit=cpu_limit,
        language=language
    )
    db_session.add(new_server)
    db_session.commit()
    return jsonify({"success": True, "message": f"✅ تم إنشاء {name}", "folder": folder, "port": assigned_port})


# ============== API Docker ==============
@app.route('/api/docker/status')
def docker_status():
    if "username" not in session:
        return jsonify({"success": False}), 401
    return jsonify({"success": True, "available": DOCKER_AVAILABLE})

@app.route('/api/docker/container_logs/<folder>')
def container_logs(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"success": False}), 403
    logs = get_docker_logs(folder) or "لا توجد logs من Docker"
    return jsonify({"success": True, "logs": logs})

@app.route('/api/docker/generate_dockerfile/<folder>', methods=['POST'])
def api_generate_dockerfile(folder):
    if "username" not in session:
        return jsonify({"success": False}), 401
    srv = db_session.query(Server).filter_by(folder=folder).first()
    if not srv or srv.owner != session["username"]:
        return jsonify({"success": False}), 403
    content = generate_dockerfile(srv.language, srv.path)
    if not content:
        return jsonify({"success": False, "message": "لغة غير مدعومة"})
    dockerfile_path = os.path.join(srv.path, "Dockerfile")
    with open(dockerfile_path, 'w') as f:
        f.write(content)
    return jsonify({"success": True, "message": "✅ تم إنشاء Dockerfile", "content": content})

# ============== Admin: تحميل ملفات أي مستخدم ==============
@app.route('/api/admin/download_user_file', methods=['POST'])
def admin_download_user_file():
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({"success": False, "message": "غير مصرح"}), 403
    data = request.get_json()
    target_user = data.get("username", "").strip()
    server_folder = data.get("folder", "").strip()
    file_path = data.get("file_path", "").strip()
    
    if not target_user or not server_folder or not file_path:
        return jsonify({"success": False, "message": "بيانات ناقصة"})
    
    srv = db_session.query(Server).filter_by(folder=server_folder, owner=target_user).first()
    if not srv:
        return jsonify({"success": False, "message": "السيرفر غير موجود"})
    
    full_path = os.path.join(srv.path, file_path)
    if ".." in full_path or not full_path.startswith(srv.path):
        return jsonify({"success": False, "message": "مسار غير صالح"})
    
    if not os.path.exists(full_path):
        return jsonify({"success": False, "message": "الملف غير موجود"})
    
    from flask import send_file
    return send_file(full_path, as_attachment=True, download_name=os.path.basename(full_path))

@app.route('/api/admin/list_user_servers/<username>')
def admin_list_user_servers(username):
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({"success": False}), 403
    servers = db_session.query(Server).filter_by(owner=username).all()
    return jsonify({"success": True, "servers": [
        {"folder": s.folder, "name": s.name, "status": s.status, "language": s.language}
        for s in servers
    ]})

@app.route('/api/admin/list_user_files/<username>/<folder>')
def admin_list_user_files(username, folder):
    if "username" not in session or not is_admin(session["username"]):
        return jsonify({"success": False}), 403
    srv = db_session.query(Server).filter_by(folder=folder, owner=username).first()
    if not srv:
        return jsonify({"success": False})
    files = []
    try:
        for f in os.listdir(srv.path):
            if f in ['out.log', 'meta.json']:
                continue
            fpath = os.path.join(srv.path, f)
            stat = os.stat(fpath)
            size_bytes = stat.st_size
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024*1024:
                size_str = f"{size_bytes/1024:.1f} KB"
            else:
                size_str = f"{size_bytes/(1024*1024):.1f} MB"
            files.append({"name": f, "size": size_str, "is_dir": os.path.isdir(fpath), "path": f})
    except:
        pass
    return jsonify({"success": True, "files": files, "server_path": srv.path})

# ============== التشغيل النهائي والنظام الأساسي ==============
if __name__ == "__main__":
    # تشغيل نظام Keep-Alive في خيط منفصل (Background Thread) ليعمل تلقائياً مع السيرفر
    keep_alive_thread = threading.Thread(target=run_keep_alive_daemon, daemon=True)
    keep_alive_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


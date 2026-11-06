from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os, uuid, urllib.parse
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
app.secret_key = "change-this-to-random-secret-key-2024"

# ---------- FIREBASE SETUP ----------
FIREBASE_KEY_PATH = os.environ.get("FIREBASE_KEY_PATH", "/etc/secrets/firebase-key.json")
if not os.path.exists(FIREBASE_KEY_PATH):
    FIREBASE_KEY_PATH = "firebase-key.json"

cred = credentials.Certificate(FIREBASE_KEY_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ---------- LOCAL STORAGE ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_EBOOKS = os.path.join(BASE_DIR, "static", "ebooks")
UPLOAD_COVERS = os.path.join(BASE_DIR, "static", "images")
os.makedirs(UPLOAD_EBOOKS, exist_ok=True)
os.makedirs(UPLOAD_COVERS, exist_ok=True)

ALLOWED_EBOOK_EXT = {"pdf", "epub", "mobi"}
ALLOWED_IMG_EXT = {"png", "jpg", "jpeg", "webp"}

ADMIN_USER = "business10"
ADMIN_PASS_HASH = generate_password_hash("krp10x")

WHATSAPP_NUMBER = "923700157610"          
ACCOUNT_TITLE = "SYED AFFAN SAEED"
ACCOUNT_NUMBER_DISPLAY = "0370-0157610"

def allowed_file(filename, allowed):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed

def normalize_phone(phone):
    p = phone.replace("-", "").replace(" ", "").replace("+", "")
    if p.startswith("92"): return p
    if p.startswith("0"): return "92" + p[1:]
    return "92" + p

# ---------- PUBLIC ROUTES ----------
@app.route("/")
def index():
    books_ref = db.collection('books').where('is_deleted', '==', False).order_by('created_at', direction=firestore.Query.DESCENDING).stream()
    books = []
    for doc in books_ref:
        b = doc.to_dict()
        b['id'] = doc.id
        books.append(b)
    return render_template("index.html", books=books)

@app.route("/book/<book_id>")
def book_detail(book_id):
    doc = db.collection('books').document(book_id).get()
    if not doc.exists or doc.to_dict().get('is_deleted'):
        flash("Book not found", "error")
        return redirect(url_for("index"))
    book = doc.to_dict()
    book['id'] = doc.id
    return render_template("book_detail.html", book=book)

# ---------- CHECKOUT ----------
@app.route("/checkout/<book_id>", methods=["GET", "POST"])
def checkout(book_id):
    doc = db.collection('books').document(book_id).get()
    if not doc.exists or doc.to_dict().get('is_deleted'):
        flash("Book not found", "error")
        return redirect(url_for("index"))
    book = doc.to_dict()
    book['id'] = doc.id

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        method = request.form.get("payment_method", "").strip()
        sender = request.form.get("sender_number", "").strip()
        txn = request.form.get("transaction_id", "").strip()

        if not all([name, email, phone, method, txn]):
            flash("Please fill all required fields including Transaction ID", "error")
            return redirect(url_for("checkout", book_id=book_id))

        order_id = "ORD-" + uuid.uuid4().hex[:10].upper()
        
        order_data = {
            "order_id": order_id,
            "book_id": book_id,
            "book_title": book['title'],
            "buyer_name": name,
            "buyer_email": email,
            "buyer_phone": phone,
            "payment_method": method,
            "sender_number": sender,
            "transaction_id": txn,
            "amount": book['price'],
            "status": "pending",
            "created_at": datetime.now(),
            "verified_at": None
        }
        db.collection('orders').document(order_id).set(order_data)

        wa_text = (
            f"*New E-Book Order*\n"
            f"Order ID: {order_id}\n"
            f"Book: {book['title']}\n"
            f"Amount: Rs. {book['price']:.0f}\n"
            f"Buyer: {name}\n"
            f"Phone: {phone}\n"
            f"Payment Method: {method}\n"
            f"Sender #: {sender}\n"
            f"Transaction ID (TID): {txn}"
        )
        wa_url = "https://wa.me/" + WHATSAPP_NUMBER + "?text=" + urllib.parse.quote(wa_text)
        flash(f"Order {order_id} placed! WhatsApp will open — press Send to notify us.", "success")
        return redirect(wa_url)

    return render_template("checkout.html", book=book,
                           account_title=ACCOUNT_TITLE,
                           account_number=ACCOUNT_NUMBER_DISPLAY)

# ---------- VERIFY / STATUS ----------
@app.route("/verify/<order_id>")
def verify_payment(order_id):
    doc = db.collection('orders').document(order_id).get()
    if not doc.exists:
        flash("Order not found", "error")
        return redirect(url_for("index"))
    order = doc.to_dict()
    order['order_id'] = doc.id
    
    if order.get('book_id'):
        book_doc = db.collection('books').document(order['book_id']).get()
        order['is_deleted'] = book_doc.to_dict().get('is_deleted', True) if book_doc.exists else True
    
    return render_template("verify_payment.html", order=order, whatsapp=WHATSAPP_NUMBER)

@app.route("/check-status/<order_id>")
def check_status(order_id):
    doc = db.collection('orders').document(order_id).get()
    if not doc.exists:
        return jsonify({"status": "not_found"}), 404
    return jsonify({"status": doc.to_dict().get('status')})

# ---------- DOWNLOAD ----------
@app.route("/download/<order_id>")
def download(order_id):
    doc = db.collection('orders').document(order_id).get()
    if not doc.exists:
        flash("Order not found", "error")
        return redirect(url_for("index"))
    order = doc.to_dict()

    if order.get("status") != "verified":
        flash("Payment not verified yet. Download is not available.", "error")
        return redirect(url_for("verify_payment", order_id=order_id))

    file_path = order.get('file_path')
    
    if not file_path:
        flash(f"⚠️ File record missing. Contact admin: {ACCOUNT_NUMBER_DISPLAY}", "error")
        return redirect(url_for("my_downloads"))

    try:
        file_ext = file_path.split('.')[-1]
        download_name = f"{order.get('book_title', 'Book')}.{file_ext}"
        return send_from_directory(UPLOAD_EBOOKS, file_path, as_attachment=True, download_name=download_name)
    except FileNotFoundError:
        flash(f"⚠️ This e-book file has been removed from the server. Please contact admin: {ACCOUNT_NUMBER_DISPLAY}", "error")
        return redirect(url_for("my_downloads"))

@app.route("/my-downloads", methods=["GET", "POST"])
def my_downloads():
    orders = []
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        orders_ref = db.collection('orders').where('buyer_email', '==', email).stream()
        
        for doc in orders_ref:
            o = doc.to_dict()
            o['order_id'] = doc.id
            if o.get('book_id'):
                book_doc = db.collection('books').document(o['book_id']).get()
                o['is_deleted'] = book_doc.to_dict().get('is_deleted', True) if book_doc.exists else True
            orders.append(o)
            
        orders.sort(key=lambda x: x.get('created_at', datetime.min), reverse=True)
        
    return render_template("my_downloads.html", orders=orders, email=email,
                           account_number=ACCOUNT_NUMBER_DISPLAY)

# ---------- ADMIN ----------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        if u == ADMIN_USER and check_password_hash(ADMIN_PASS_HASH, p):
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        flash("Invalid credentials", "error")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

def admin_required():
    return session.get("admin") is True

@app.route("/admin/dashboard")
def admin_dashboard():
    if not admin_required():
        return redirect(url_for("admin_login"))
    
    books_ref = db.collection('books').where('is_deleted', '==', False).order_by('created_at', direction=firestore.Query.DESCENDING).stream()
    books = []
    for doc in books_ref:
        b = doc.to_dict()
        b['id'] = doc.id
        books.append(b)
        
    orders_ref = db.collection('orders').order_by('created_at', direction=firestore.Query.DESCENDING).stream()
    orders = []
    total_revenue = 0
    verified_count = 0
    pending_count = 0

    for doc in orders_ref:
        o = doc.to_dict()
        o['order_id'] = doc.id
        orders.append(o)
        
        if o.get('status') == 'verified':
            total_revenue += o.get('amount', 0)
            verified_count += 1
        elif o.get('status') == 'pending':
            pending_count += 1

    return render_template("admin_dashboard.html", 
                           books=books, 
                           orders=orders,
                           total_revenue=total_revenue,
                           verified_count=verified_count,
                           pending_count=pending_count,
                           total_books=len(books),
                           whatsapp=WHATSAPP_NUMBER)

@app.route("/admin/upload", methods=["GET", "POST"])
def admin_upload():
    if not admin_required():
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        desc = request.form.get("description", "").strip()
        price = request.form.get("price", "0")
        old_price = request.form.get("old_price", "0")
        show_sale = request.form.get("show_sale") == "on"
        
        ebook = request.files.get("ebook")
        cover = request.files.get("cover")

        if not title or not author or not ebook or ebook.filename == "":
            flash("Title, author and ebook file are required", "error")
            return redirect(url_for("admin_upload"))

        safe_name = secure_filename(ebook.filename)
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        ebook.save(os.path.join(UPLOAD_EBOOKS, unique_name))

        cover_name = ""
        if cover and cover.filename and allowed_file(cover.filename, ALLOWED_IMG_EXT):
            cname = f"{uuid.uuid4().hex}_{secure_filename(cover.filename)}"
            cover.save(os.path.join(UPLOAD_COVERS, cname))
            cover_name = cname

        book_data = {
            "title": title,
            "author": author,
            "description": desc,
            "price": float(price),
            "old_price": float(old_price) if show_sale else 0,
            "show_sale": show_sale,
            "cover_image": cover_name, 
            "file_path": unique_name,
            "is_deleted": False,
            "created_at": datetime.now()
        }
        db.collection('books').add(book_data)

        flash("Book uploaded successfully!", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_upload.html")

@app.route("/admin/edit-book/<book_id>", methods=["GET", "POST"])
def admin_edit_book(book_id):
    if not admin_required():
        return redirect(url_for("admin_login"))

    doc_ref = db.collection('books').document(book_id)
    doc = doc_ref.get()
    if not doc.exists:
        flash("Book not found", "error")
        return redirect(url_for("admin_dashboard"))
        
    book = doc.to_dict()
    book['id'] = doc.id

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        author = request.form.get("author", "").strip()
        desc = request.form.get("description", "").strip()
        price = request.form.get("price", "0")
        old_price = request.form.get("old_price", "0")
        show_sale = request.form.get("show_sale") == "on"
        
        ebook = request.files.get("ebook")
        cover = request.files.get("cover")

        update_data = {
            "title": title,
            "author": author,
            "description": desc,
            "price": float(price),
            "old_price": float(old_price) if show_sale else 0,
            "show_sale": show_sale
        }

        if ebook and ebook.filename != "":
            safe_name = secure_filename(ebook.filename)
            unique_name = f"{uuid.uuid4().hex}_{safe_name}"
            ebook.save(os.path.join(UPLOAD_EBOOKS, unique_name))
            update_data["file_path"] = unique_name

        if cover and cover.filename != "" and allowed_file(cover.filename, ALLOWED_IMG_EXT):
            cname = f"{uuid.uuid4().hex}_{secure_filename(cover.filename)}"
            cover.save(os.path.join(UPLOAD_COVERS, cname))
            update_data["cover_image"] = cname

        doc_ref.update(update_data)
        flash("Book updated successfully!", "success")
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_upload.html", book=book, is_edit=True)

@app.route("/admin/verify-order/<order_id>", methods=["POST"])
def admin_verify_order(order_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    action = request.form.get("action")
    status = "verified" if action == "approve" else "rejected"
    
    doc_ref = db.collection('orders').document(order_id)
    doc = doc_ref.get()
    if not doc.exists:
        flash("Order not found", "error")
        return redirect(url_for("admin_dashboard"))
        
    order = doc.to_dict()
    doc_ref.update({
        "status": status,
        "verified_at": datetime.now()
    })

    if status == "verified":
        buyer_wa = normalize_phone(order["buyer_phone"])
        base_url = os.environ.get("RENDER_EXTERNAL_URL", "https://karobar-rehnuma.onrender.com")
        wa_text = (
            f"*Payment Verified* ✅\n\n"
            f"Hi {order['buyer_name']},\n"
            f"Your payment for *{order.get('book_title', 'your e-book')}* has been verified!\n\n"
            f"Order ID: {order_id}\n"
            f"Download here: {base_url}/verify/{order_id}\n\n"
            f"Thank you for shopping with us!"
        )
        wa_url = f"https://wa.me/{buyer_wa}?text={urllib.parse.quote(wa_text)}"
        flash(f"Order {order_id} verified! WhatsApp will open to notify the customer.", "success")
        return redirect(wa_url)

    flash(f"Order {order_id} {status}.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete-book/<book_id>", methods=["POST"])
def admin_delete_book(book_id):
    if not admin_required():
        return redirect(url_for("admin_login"))
    db.collection('books').document(book_id).update({"is_deleted": True})
    flash("Book removed from store.", "success")
    return redirect(url_for("admin_dashboard"))

# ---------- RUN ----------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
# ---------- DOWNLOAD (FIXED ERROR 500) ----------
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
        flash(f"⚠️ File record missing in database. Contact admin: {ACCOUNT_NUMBER_DISPLAY}", "error")
        return redirect(url_for("my_downloads"))

    try:
        # File ka extension nikalne ke liye
        file_ext = file_path.split('.')[-1]
        download_name = f"{order.get('book_title', 'Book')}.{file_ext}"
        
        # File ko bhejne ki koshish karein
        return send_from_directory(UPLOAD_EBOOKS, file_path, as_attachment=True, download_name=download_name)
    
    except FileNotFoundError:
        # Agar file Render se delete ho chuki ho
        flash(f"⚠️ This e-book file has been removed from the server. Please contact admin on WhatsApp: {ACCOUNT_NUMBER_DISPLAY}", "error")
        return redirect(url_for("my_downloads"))
    
    except Exception as e:
        # Kisi aur error ki soorat mein
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for("my_downloads"))
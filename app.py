import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from supabase import create_client, Client
from datetime import datetime
import pytz
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dheeni_drive_ist_2026')

# --- SUPABASE CONFIG ---
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(URL, KEY)

# --- AUTH DECORATOR ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- HELPERS ---
def get_today_start_iso():
    """Calculates 12:00 AM Today in IST for filtering."""
    tz = pytz.timezone('Asia/Kolkata')
    today_start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return today_start.isoformat()

def format_timestamp(ts_string):
    """Converts Supabase UTC string to IST Display Time."""
    try:
        dt_utc = datetime.fromisoformat(ts_string.replace('Z', '+00:00'))
        dt_ist = dt_utc.astimezone(pytz.timezone('Asia/Kolkata'))
        return dt_ist.strftime('%I:%M %p')
    except: return ""

# --- AUTH ROUTES ---

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/auth/google')
def auth_google():
    """Triggers Google OAuth via Supabase."""
    # Logic: Use the RENDER_EXTERNAL_URL if it exists, otherwise fallback to local
    base_url = os.environ.get('RENDER_EXTERNAL_URL', 'http://127.0.0.1:5000')
    redirect_url = f"{base_url}/auth/callback"
    
    res = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {
            "redirect_to": redirect_url
        }
    })
    return redirect(res.url)

@app.route('/auth/callback')
def auth_callback():
    """Landing page for Google Redirect."""
    return render_template('callback.html')

@app.route('/set-session-from-callback', methods=['POST'])
def set_session_from_callback():
    """Exchanges Google Code for a Flask Session."""
    data = request.json
    code = data.get('code')
    if not code:
        return jsonify({"status": "error"}), 400
    
    try:
        res = supabase.auth.exchange_code_for_session({"auth_code": code})
        user = res.user
        session['user_id'] = user.id
        session['user_name'] = user.user_metadata.get('full_name', 'Verified User')
        session['user_email'] = user.email
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"Auth Exchange Error: {e}")
        return jsonify({"status": "error"}), 400

# --- APP ROUTES ---

@app.route('/')
@login_required
def index():
    filter_type = request.args.get('filter', 'all')
    my_activity = request.args.get('my_activity') == 'true'
    user_email = session.get('user_email')
    
    today_iso = get_today_start_iso()

    try:
        # Fetch today's rides with nested bookings
        query = supabase.table("ride").select("*, booking(*)").gte("created_at", today_iso)
        
        if filter_type == 'bike':
            query = query.eq("vehicle_type", "Two-wheeler")
        elif filter_type == 'car':
            query = query.eq("vehicle_type", "Car")
        
        response = query.execute()
        all_rides = response.data
    except: all_rides = []

    display_rides = []
    for ride in all_rides:
        ride['formatted_time'] = format_timestamp(ride.get('created_at'))
        is_driver = ride.get('driver_email') == user_email
        is_seeker = any(b['seeker_email'] == user_email for b in ride.get('booking', []))
        
        if not my_activity or (is_driver or is_seeker):
            display_rides.append(ride)

    return render_template('index.html', rides=display_rides, current_filter=filter_type, my_activity=my_activity)

@app.route('/offer', methods=['POST'])
@login_required
def offer_ride():
    data = {
        "driver_name": session['user_name'],
        "driver_email": session['user_email'],
        "driver_phone": request.form['phone'],
        "vehicle_type": request.form['vehicle'],
        "total_seats": int(request.form['seats']),
        "seats_taken": 0,
        "departure_time": request.form['time'],
        "source_url": request.form['source_url'],
        "destination_url": request.form['destination_url']
    }
    supabase.table("ride").insert(data).execute()
    flash("Ride published successfully!")
    return redirect(url_for('index'))

@app.route('/join/<int:ride_id>', methods=['POST'])
@login_required
def join_ride(ride_id):
    ride_resp = supabase.table("ride").select("total_seats, seats_taken").eq("id", ride_id).single().execute()
    ride = ride_resp.data

    if ride['seats_taken'] < ride['total_seats']:
        booking_data = {
            "ride_id": ride_id,
            "seeker_name": session['user_name'],
            "seeker_email": session['user_email'],
            "seeker_phone": request.form['seeker_phone']
        }
        supabase.table("booking").insert(booking_data).execute()
        supabase.table("ride").update({"seats_taken": ride['seats_taken'] + 1}).eq("id", ride_id).execute()
        flash("Seat secured! InshaAllah.")
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
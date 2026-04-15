import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from supabase import create_client, Client
from datetime import datetime
import pytz
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'jumma_drive_final_2026')

# --- SUPABASE CONFIG ---
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(URL, KEY)

# --- AUTH DECORATOR ---
def get_last_ride_details(email):
    try:
        # Fetch the single latest ride by this user, regardless of date
        res = supabase.table("ride").select("*").eq("driver_email", email).order("created_at", desc=True).limit(1).execute()
        return res.data[0] if res.data else None
    except:
        return None
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- HELPERS ---
def get_today_start_iso():
    tz = pytz.timezone('Asia/Kolkata')
    return datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

def format_timestamp(ts_string):
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
    base_url = os.environ.get('RENDER_EXTERNAL_URL', 'http://127.0.0.1:5000')
    res = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {"redirect_to": f"{base_url}/auth/callback"}
    })
    return redirect(res.url)

@app.route('/auth/callback')
def auth_callback():
    return render_template('callback.html')

@app.route('/set-session-from-callback', methods=['POST'])
def set_session_from_callback():
    code = request.json.get('code')
    try:
        res = supabase.auth.exchange_code_for_session({"auth_code": code})
        session['user_id'] = res.user.id
        session['user_name'] = res.user.user_metadata.get('full_name', 'User')
        session['user_email'] = res.user.email
        return jsonify({"status": "success"})
    except: return jsonify({"status": "error"}), 400

# --- MAIN ROUTES ---

@app.route('/')
@login_required
def index():
    filter_type = request.args.get('filter', 'all')
    sort_by = request.args.get('sort', 'time') # Default: Departure Time
    my_activity = request.args.get('my_activity') == 'true'
    user_email = session.get('user_email')
    last_ride = get_last_ride_details(user_email)
    
    try:
        query = supabase.table("ride").select("*, booking(*)").gte("created_at", get_today_start_iso()).eq("is_active", True)
        if filter_type == 'bike': query = query.eq("vehicle_type", "Two-wheeler")
        elif filter_type == 'car': query = query.eq("vehicle_type", "Car")
        
        rides = query.execute().data
    except: rides = []

    processed_rides = []
    for r in rides:
        r['formatted_time'] = format_timestamp(r.get('created_at'))
        r['active_bookings'] = [b for b in r.get('booking', []) if b.get('is_active', True)]
        r['seats_left'] = r['total_seats'] - r['seats_taken']
        
        is_owner = r.get('driver_email') == user_email
        is_joined = any(b['seeker_email'] == user_email for b in r['active_bookings'])
        
        if not my_activity or (is_owner or is_joined):
            processed_rides.append(r)

    # SORTING LOGIC
    if sort_by == 'availability':
        processed_rides.sort(key=lambda x: x['seats_left'], reverse=True)
    else:
        processed_rides.sort(key=lambda x: x['departure_time'])

    return render_template('index.html', rides=processed_rides,last_ride=last_ride, current_filter=filter_type, 
                           my_activity=my_activity, current_sort=sort_by)

@app.route('/offer', methods=['POST'])
@login_required
def offer_ride():
    is_rental = request.form.get('is_rental') == 'true'
    fare = int(request.form.get('fare', 0)) if is_rental else 0

    supabase.table("ride").insert({
        "driver_name": session['user_name'], "driver_email": session['user_email'],
        "driver_phone": request.form['phone'], "vehicle_type": request.form['vehicle'],
        "total_seats": int(request.form['seats']), "seats_taken": 0,
        "departure_time": request.form['time'], "source_url": request.form['source_url'],
        "destination_url": request.form['destination_url'],
        "is_rental": is_rental, "fare_per_person": fare
    }).execute()
    flash("Ride published on Jumma Drive!")
    return redirect(url_for('index'))

@app.route('/edit-ride/<int:ride_id>', methods=['POST'])
@login_required
def edit_ride(ride_id):
    supabase.table("ride").update({
        "vehicle_type": request.form['vehicle'],
        "total_seats": int(request.form['seats']),
        "departure_time": request.form['time'],
        "updated_at": datetime.now(pytz.utc).isoformat()
    }).eq("id", ride_id).eq("driver_email", session['user_email']).execute()
    flash("Ride updated!")
    return redirect(url_for('index'))

@app.route('/remove-ride/<int:ride_id>', methods=['POST'])
@login_required
def remove_ride(ride_id):
    supabase.table("ride").update({"is_active": False}).eq("id", ride_id).eq("driver_email", session['user_email']).execute()
    flash("Ride removed.")
    return redirect(url_for('index'))

@app.route('/join/<int:ride_id>', methods=['POST'])
@login_required
def join_ride(ride_id):
    ride = supabase.table("ride").select("seats_taken, total_seats").eq("id", ride_id).single().execute().data
    if ride['seats_taken'] < ride['total_seats']:
        supabase.table("booking").insert({
            "ride_id": ride_id, "seeker_name": session['user_name'],
            "seeker_email": session['user_email'], "seeker_phone": request.form['seeker_phone']
        }).execute()
        supabase.table("ride").update({"seats_taken": ride['seats_taken'] + 1}).eq("id", ride_id).execute()
        flash("Seat secured!")
    return redirect(url_for('index'))

@app.route('/cancel-booking/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    booking = supabase.table("booking").select("ride_id").eq("id", booking_id).eq("seeker_email", session['user_email']).single().execute().data
    if booking:
        supabase.table("booking").update({"is_active": False}).eq("id", booking_id).execute()
        ride = supabase.table("ride").select("seats_taken").eq("id", booking['ride_id']).single().execute().data
        supabase.table("ride").update({"seats_taken": max(0, ride['seats_taken'] - 1)}).eq("id", booking['ride_id']).execute()
        flash("Booking cancelled.")
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
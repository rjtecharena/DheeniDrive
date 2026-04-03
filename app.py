from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///masjid_rides.db'
app.config['SECRET_KEY'] = 'masjid_community_2026'
db = SQLAlchemy(app)

# Database Models
class Ride(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_name = db.Column(db.String(100), nullable=False)
    driver_phone = db.Column(db.String(20), nullable=False)
    vehicle_type = db.Column(db.String(20)) # 'Two-wheeler' or 'Car'
    total_seats = db.Column(db.Integer, nullable=False)
    seats_taken = db.Column(db.Integer, default=0)
    departure_time = db.Column(db.String(20))
    source_url = db.Column(db.String(500))      # Google Maps Link
    destination_url = db.Column(db.String(500)) # Google Maps Link
    bookings = db.relationship('Booking', backref='ride', lazy=True, cascade="all, delete-orphan")

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ride_id = db.Column(db.Integer, db.ForeignKey('ride.id'), nullable=False)
    seeker_name = db.Column(db.String(100), nullable=False)
    seeker_phone = db.Column(db.String(20), nullable=False)

# Routes
@app.route('/')
def index():
    filter_type = request.args.get('filter', 'all')
    sort_by = request.args.get('sort', 'type') # Default sort by Vehicle Type (Bikes first)

    query = Ride.query

    # 1. Filtering
    if filter_type == 'bike':
        query = query.filter_by(vehicle_type='Two-wheeler')
    elif filter_type == 'car':
        query = query.filter_by(vehicle_type='Car')

    # 2. Sorting Logic
    if sort_by == 'availability':
        # Order by most seats available
        query = query.order_by((Ride.total_seats - Ride.seats_taken).desc())
    else:
        # Default: Two-wheelers first, then available seats
        query = query.order_by(desc(Ride.vehicle_type), (Ride.total_seats - Ride.seats_taken).desc())

    rides = query.all()
    return render_template('index.html', rides=rides, current_filter=filter_type)

@app.route('/offer', methods=['POST'])
def offer_ride():
    new_ride = Ride(
        driver_name=request.form['name'],
        driver_phone=request.form['phone'],
        vehicle_type=request.form['vehicle'],
        total_seats=int(request.form['seats']),
        departure_time=request.form['time'],
        source_url=request.form['source_url'],
        destination_url=request.form['destination_url']
    )
    db.session.add(new_ride)
    db.session.commit()
    flash("Ride posted! Share the link in the WhatsApp group.")
    return redirect(url_for('index'))

@app.route('/join/<int:ride_id>', methods=['POST'])
def join_ride(ride_id):
    ride = Ride.query.get_or_404(ride_id)
    if ride.seats_taken < ride.total_seats:
        new_booking = Booking(
            ride_id=ride.id, 
            seeker_name=request.form['seeker_name'],
            seeker_phone=request.form['seeker_phone']
        )
        ride.seats_taken += 1
        db.session.add(new_booking)
        db.session.commit()
        flash(f"Seat booked with {ride.driver_name}!")
    return redirect(url_for('index'))

@app.route('/admin/reset', methods=['POST'])
def reset_data():
    db.session.query(Booking).delete()
    db.session.query(Ride).delete()
    db.session.commit()
    flash("All data cleared for the new week.")
    return redirect(url_for('index'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
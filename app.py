import os
import time
import sqlite3
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit

app = Flask(__name__, static_folder=".", static_url_path="")
app.config['SECRET_KEY'] = 'secret'
CORS(app)

db_path = os.path.join(os.path.dirname(__file__), 'HouseSalesSeattle.db')
#connection = sqlite3.connect(db_path, check_same_thread=False)
#cursor = connection.cursor()

socketio = SocketIO(app, cors_allowed_origins="*")

def get_db_connection():
    #return sqlite3.connect(db_path, check_same_thread=False)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection

#stores all bids 
bids = []


#stores bidder alias name
bidder_aliases = {}


def get_bidder_alias(name, email, phone):
    bidder_key = f"bidder_{name}_{email}_{phone}"
    
    if bidder_key not in bidder_aliases:
        bidder_aliases[bidder_key] = f"Bidder {len(bidder_aliases) + 1}"
        
    return bidder_aliases[bidder_key]

def anonymize_bids():
    anon_bids = []
    
    for bid in bids:
        anon_bids.append({
            "bidder":bid["bidder"],
            "amount": bid["amount"],
            "property": bid["property"],
            "time": bid["time"]
        })
        
    return anon_bids







@app.route("/")
def home():
    return send_from_directory(".", "husindex.html")


@app.route("/live-bidding")
def live_bidding():
    return send_from_directory(".", "live-bidding.html")



@app.route("/realtor")
def realtor():
    return send_from_directory(".", "realtor.html")


@app.route("/market-analysis")
def market_analysis():
    return send_from_directory(".", "market-analysis.html")



@app.route("/api/properties")
def get_properties():
    zip_code = request.args.get("zip_code")
    min_bedrooms = request.args.get("min_bedrooms", type=int)

    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=12, type=int)

    if page < 1:
        page = 1

    if per_page < 1:
        per_page = 12

    # if per_page > 15:
    #     per_page = 15
    
    if per_page > 1000:
        per_page = 1000    

    offset = (page - 1) * per_page

    base_query = """
        FROM HouseSalesSeattle
        WHERE 1=1
    """

    params = []

    if zip_code:
        base_query += " AND zip_code = ?"
        params.append(zip_code)

    if min_bedrooms is not None:
        base_query += " AND Bedrooms >= ?"
        params.append(min_bedrooms)

    count_query = "SELECT COUNT(*) " + base_query

    data_query = """
        SELECT 
            SalesID,
            Image,
            zip_code,
            AdjSalePrice,
            Bedrooms,
            Bathrooms,
            SqMTotLiving
    """ + base_query + """
        ORDER BY SalesID
        LIMIT ? OFFSET ?
    """

    connection = get_db_connection()
    cursor = connection.cursor()
    
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]

    cursor.execute(data_query, params + [per_page, offset])
    rows = cursor.fetchall()
    
    connection.close()

    properties = []

    for row in rows:
        properties.append({
            "SalesID": row["SalesID"],
            "Image": row["Image"],
            "zip_code": row["zip_code"],
            "AdjSalePrice": row["AdjSalePrice"],
            "Bedrooms": row["Bedrooms"],
            "Bathrooms": row["Bathrooms"],
            "SqMTotLiving": row["SqMTotLiving"]
        })

    return jsonify({
        "properties": properties,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page
    })

@app.route("/api/bids")
def get_bids():
    return jsonify({
        "anon_bids": anonymize_bids(),
        "realtor_bids": bids
    })

@app.route("/api/realtor-login", methods=["POST"])
def realtor_login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
 
    # Hardcoded realtor credentials
    REALTOR_USERNAME = "realtor"
    REALTOR_PASSWORD = "123"
 
    if username == REALTOR_USERNAME and password == REALTOR_PASSWORD:
        return jsonify({"success": True, "message": "Login successful"})
    else:
        return jsonify({"success": False, "message": "Invalid username or password"}), 401


@app.route("/api/price-per-zip")
def price_per_zip():
    connection = get_db_connection()
    cursor = connection.cursor()
    
    cursor.execute("""
        SELECT zip_code, AVG(AdjSalePrice) AS average_price
        FROM HouseSalesSeattle
        GROUP BY zip_code
        ORDER BY average_price DESC
        LIMIT 10
    """)

    rows = cursor.fetchall()
    
    connection.close()

    data = {
        "labels": [row["zip_code"] for row in rows],
        "values": [round(row["average_price"], 2) for row in rows]
    }

    return jsonify(data)



@socketio.on("connect")
def handle_connect():
    emit("bids_update", anonymize_bids())
    emit("realtor_bids_update", bids)


@socketio.on("new_bid")
def handle_new_bid(data):
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()
    amount = data.get("amount")
    property_name = data.get("property", "Selected property").strip()

    if not name or not email or not phone or not amount:
        emit("bid_error", {
            "message": "Name, email, phone and amount are required."
        })
        return

    try:
        amount = int(amount)
    except ValueError:
        emit("bid_error", {
            "message": "Bid amount must be a number."
        })
        return

    if amount <= 0:
        emit("bid_error", {
            "message": "Bid amount must be greater than 0."
        })
        return
    
    existing_bids = [
        b for b in bids
        if str(b["property"]) == str(property_name)
    ]

    highest_bid = max(
        [b["amount"] for b in existing_bids],
        default=0
    )

    if amount <= highest_bid:
        emit("bid_error", {
            "message": "Bid must be higher than current highest bid."
        })
        return

    bidder_alias = get_bidder_alias(name, email, phone)

    bid = {
        "name": name,
        "email": email,
        "phone": phone,
        "bidder": bidder_alias,
        "amount": amount,
        "property": property_name,
        "time": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    bids.append(bid)

    socketio.emit("bids_update", anonymize_bids())
    socketio.emit("realtor_bids_update", bids)


if __name__ == "__main__":
    socketio.run(app, debug=True)

#!/usr/bin/env python3
"""
Call Tracker — receives Asterisk webhook events and exposes call state via REST API.

Endpoints:
  POST /                       <- Asterisk posts events here
  GET  /calls/active           <- currently active calls (ringing + answered)
  GET  /calls/recent?limit=100 <- last N calls (active + completed)
  GET  /calls/<call_id>        <- single call detail
"""
from flask import Flask, request, jsonify
from datetime import datetime
from collections import OrderedDict
import threading

app = Flask(__name__)

# Thread-safe call store
# OrderedDict keeps insertion order — newest calls at the end
_lock = threading.Lock()
_calls = OrderedDict()  # call_id -> dict
MAX_HISTORY = 500       # keep last 500 calls in memory


def now_iso():
    return datetime.now().isoformat(timespec='seconds')


def get_call(call_id):
    return _calls.get(call_id)


def upsert_call(call_id, updates):
    with _lock:
        if call_id not in _calls:
            _calls[call_id] = {
                'call_id':     call_id,
                'caller':      '',
                'callee':      '',
                'status':      'unknown',
                'started_at':  now_iso(),
                'answered_at': None,
                'ended_at':    None,
                'duration':    None,
                'billsec':     None,
                'hangup_by':   None,
                'hangup_cause': None,
            }
        _calls[call_id].update(updates)

        # Trim to MAX_HISTORY — remove oldest completed calls first
        if len(_calls) > MAX_HISTORY:
            completed = [k for k, v in _calls.items() if v['status'] == 'hangup']
            for k in completed[:len(_calls) - MAX_HISTORY]:
                del _calls[k]


# ─── Webhook receiver ────────────────────────────────────────────────────────

@app.route('/', methods=['POST'])
def receive_event():
    data = request.get_json(silent=True) or {}
    event   = data.get('event', '')
    call_id = data.get('call_id', '')

    if not call_id:
        return 'OK', 200

    if event == 'ringing':
        upsert_call(call_id, {
            'caller':     data.get('caller', ''),
            'callee':     data.get('callee', ''),
            'status':     'ringing',
            'started_at': now_iso(),
        })

    elif event == 'answered':
        upsert_call(call_id, {
            'status':      'answered',
            'answered_at': now_iso(),
            'caller':      data.get('caller') or get_call(call_id) and get_call(call_id).get('caller', ''),
        })

    elif event == 'dial_start':
        upsert_call(call_id, {
            'caller':     data.get('caller', ''),
            'callee':     data.get('callee', ''),
            'status':     'ringing',
            'started_at': now_iso(),
        })

    elif event == 'dial_result':
        result = data.get('result', '')
        if result == 'ANSWERED':
            upsert_call(call_id, {'status': 'answered'})
        elif result in ('NOANSWER', 'BUSY', 'CANCEL', 'FAILED', 'CONGESTION'):
            upsert_call(call_id, {
                'status':   'hangup',
                'ended_at': now_iso(),
                'hangup_cause': result,
            })

    elif event == 'hangup':
        upsert_call(call_id, {
            'status':       'hangup',
            'ended_at':     now_iso(),
            'duration':     data.get('duration'),
            'billsec':      data.get('billsec'),
            'hangup_by':    data.get('hangup_by', ''),
            'hangup_cause': data.get('cause', ''),
        })

    print(f"[{now_iso()}] {event.upper():12} call_id={call_id} "
          f"caller={data.get('caller','')} callee={data.get('callee','')} "
          f"status={_calls.get(call_id, {}).get('status', '')}")

    return 'OK', 200


# ─── Query endpoints ──────────────────────────────────────────────────────────

@app.route('/calls/active', methods=['GET'])
def active_calls():
    """Returns all calls currently ringing or answered."""
    with _lock:
        active = [c for c in _calls.values() if c['status'] in ('ringing', 'answered')]
    return jsonify({
        'count': len(active),
        'calls': sorted(active, key=lambda c: c['started_at'], reverse=True)
    })


@app.route('/calls/recent', methods=['GET'])
def recent_calls():
    """Returns last N calls — active + completed. Default limit=100."""
    limit = min(int(request.args.get('limit', 100)), MAX_HISTORY)

    # Optional filters
    caller  = request.args.get('caller')
    callee  = request.args.get('callee')
    status  = request.args.get('status')

    with _lock:
        calls = list(_calls.values())

    # Apply filters
    if caller:
        calls = [c for c in calls if c['caller'] == caller]
    if callee:
        calls = [c for c in calls if c['callee'] == callee]
    if status:
        calls = [c for c in calls if c['status'] == status]

    # Most recent first
    calls = sorted(calls, key=lambda c: c['started_at'], reverse=True)[:limit]

    return jsonify({
        'count': len(calls),
        'limit': limit,
        'calls': calls
    })


@app.route('/calls/<call_id>', methods=['GET'])
def single_call(call_id):
    """Returns detail for a single call by call_id."""
    with _lock:
        call = _calls.get(call_id)
    if not call:
        return jsonify({'error': 'call not found'}), 404
    return jsonify(call)


@app.route('/stats', methods=['GET'])
def stats():
    """Quick summary stats."""
    with _lock:
        all_calls  = list(_calls.values())
    ringing  = sum(1 for c in all_calls if c['status'] == 'ringing')
    answered = sum(1 for c in all_calls if c['status'] == 'answered')
    ended    = sum(1 for c in all_calls if c['status'] == 'hangup')
    return jsonify({
        'ringing':  ringing,
        'answered': answered,
        'ended':    ended,
        'total_in_memory': len(all_calls),
    })


if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    print(f"Call tracker running on http://127.0.0.1:{port}")
    print(f"  POST /              <- Asterisk webhook")
    print(f"  GET  /calls/active  <- active calls")
    print(f"  GET  /calls/recent  <- last 100 calls")
    print(f"  GET  /calls/<id>    <- single call")
    print(f"  GET  /stats         <- summary\n")
    app.run(host='127.0.0.1', port=port, debug=False)

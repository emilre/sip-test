#!/usr/bin/env python3
"""
Call Tracker — receives Asterisk webhook events and exposes call state via REST API.

Endpoints:
  POST /                  <- Asterisk posts events here
  GET  /calls/active      <- currently active calls (ringing + answered)
  GET  /calls/recent      <- last 100 calls from memory (active + completed)
  GET  /calls/cdr         <- last 100 completed calls read directly from Asterisk CDR
  GET  /calls/<call_id>   <- single call detail
  GET  /stats             <- summary counts
"""
from flask import Flask, request, jsonify
from datetime import datetime
from collections import OrderedDict
import threading
import csv
import os

app = Flask(__name__)

CDR_FILE    = '/var/log/asterisk/cdr-csv/Master.csv'
MAX_HISTORY = 500

_lock  = threading.Lock()
_calls = OrderedDict()  # call_id -> dict


def now_iso():
    return datetime.now().isoformat(timespec='seconds')


def upsert_call(call_id, updates):
    with _lock:
        if call_id not in _calls:
            _calls[call_id] = {
                'call_id':      call_id,
                'caller':       '',
                'callee':       '',
                'status':       'unknown',
                'started_at':   now_iso(),
                'answered_at':  None,
                'ended_at':     None,
                'duration':     None,
                'billsec':      None,
                'hangup_by':    None,
                'hangup_cause': None,
            }
        _calls[call_id].update(updates)

        if len(_calls) > MAX_HISTORY:
            completed = [k for k, v in _calls.items() if v['status'] == 'hangup']
            for k in completed[:len(_calls) - MAX_HISTORY]:
                del _calls[k]


# ─── Webhook receiver ─────────────────────────────────────────────────────────

@app.route('/', methods=['POST'])
def receive_event():
    data    = request.get_json(silent=True) or {}
    event   = data.get('event', '')
    call_id = data.get('call_id', '')

    if not call_id:
        return 'OK', 200

    if event in ('ringing', 'dial_start'):
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
        })

    elif event == 'dial_result':
        result = data.get('result', '')
        if result == 'ANSWERED':
            upsert_call(call_id, {'status': 'answered'})
        elif result in ('NOANSWER', 'BUSY', 'CANCEL', 'FAILED', 'CONGESTION'):
            upsert_call(call_id, {
                'status':       'hangup',
                'ended_at':     now_iso(),
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
          f"status={_calls.get(call_id, {}).get('status', '')}")

    return 'OK', 200


# ─── Method 1: in-memory tracker ──────────────────────────────────────────────

@app.route('/calls/active', methods=['GET'])
def active_calls():
    """Active calls from in-memory state (ringing + answered)."""
    with _lock:
        active = [c for c in _calls.values() if c['status'] in ('ringing', 'answered')]
    return jsonify({
        'method': 'in-memory',
        'count':  len(active),
        'calls':  sorted(active, key=lambda c: c['started_at'], reverse=True),
    })


@app.route('/calls/recent', methods=['GET'])
def recent_calls():
    """Last 100 calls from in-memory state (active + completed)."""
    with _lock:
        calls = list(_calls.values())
    calls = sorted(calls, key=lambda c: c['started_at'], reverse=True)[:100]
    return jsonify({
        'method': 'in-memory',
        'count':  len(calls),
        'calls':  calls,
    })


# ─── Method 2: CDR direct query ───────────────────────────────────────────────

CDR_COLUMNS = [
    'accountcode', 'src', 'dst', 'dstcontext', 'clid',
    'channel', 'dstchannel', 'lastapp', 'lastdata',
    'start', 'answer', 'end', 'duration', 'billsec',
    'disposition', 'amaflags', 'uniqueid', 'userfield',
]

@app.route('/calls/cdr', methods=['GET'])
def cdr_calls():
    """Last 100 completed calls read directly from Asterisk CDR CSV."""
    if not os.path.exists(CDR_FILE):
        return jsonify({'error': f'CDR file not found: {CDR_FILE}'}), 404

    rows = []
    with open(CDR_FILE, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < len(CDR_COLUMNS):
                continue
            rec = dict(zip(CDR_COLUMNS, row))
            # Skip Local channel internal legs (;1 legs are the originating side)
            if rec['channel'].endswith(';1'):
                continue
            rows.append({
                'call_id':     rec['uniqueid'],
                'caller':      rec['src'],
                'callee':      rec['dst'],
                'channel':     rec['channel'],
                'started_at':  rec['start'],
                'answered_at': rec['answer'] if rec['answer'] != rec['start'] else None,
                'ended_at':    rec['end'],
                'duration':    rec['duration'],
                'billsec':     rec['billsec'],
                'disposition': rec['disposition'],
                'lastapp':     rec['lastapp'],
            })

    # Most recent first, last 100
    rows = sorted(rows, key=lambda r: r['started_at'], reverse=True)[:100]

    return jsonify({
        'method': 'cdr-direct',
        'source': CDR_FILE,
        'count':  len(rows),
        'calls':  rows,
    })


# ─── Single call + stats ───────────────────────────────────────────────────────

@app.route('/calls/<call_id>', methods=['GET'])
def single_call(call_id):
    with _lock:
        call = _calls.get(call_id)
    if not call:
        return jsonify({'error': 'call not found'}), 404
    return jsonify(call)


@app.route('/stats', methods=['GET'])
def stats():
    with _lock:
        all_calls = list(_calls.values())
    return jsonify({
        'ringing':         sum(1 for c in all_calls if c['status'] == 'ringing'),
        'answered':        sum(1 for c in all_calls if c['status'] == 'answered'),
        'ended':           sum(1 for c in all_calls if c['status'] == 'hangup'),
        'total_in_memory': len(all_calls),
    })


if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    print(f"Call tracker on http://127.0.0.1:{port}")
    print(f"  POST /             <- Asterisk webhooks")
    print(f"  GET  /calls/active <- active calls (in-memory)")
    print(f"  GET  /calls/recent <- last 100 calls (in-memory)")
    print(f"  GET  /calls/cdr    <- last 100 completed (CDR direct)")
    print(f"  GET  /calls/<id>   <- single call")
    print(f"  GET  /stats        <- summary\n")
    app.run(host='127.0.0.1', port=port, debug=False)

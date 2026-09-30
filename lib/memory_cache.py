"""Tiny bounded process cache in front of the persistent browse SQLite cache."""
import threading, time
_LOCK=threading.Lock(); _DATA={}; MAX_ENTRIES=256

def get(key):
    now=time.time()
    with _LOCK:
        row=_DATA.get(key)
        if not row:return None
        expires,value=row
        if expires is not None and expires<=now:_DATA.pop(key,None);return None
        return value

def put(key,value,ttl):
    expires=None if ttl is None else time.time()+max(0,ttl)
    with _LOCK:
        _DATA[key]=(expires,value)
        if len(_DATA)>MAX_ENTRIES:
            for victim in list(_DATA)[:max(1,MAX_ENTRIES//8)]:_DATA.pop(victim,None)


def clear():
    with _LOCK:_DATA.clear()

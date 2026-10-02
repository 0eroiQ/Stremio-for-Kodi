import json, platform, urllib.request, urllib.error
import xbmc, xbmcaddon, xbmcgui

API='https://mkga.tv/api/kodi/agent/pair'
addon=xbmcaddon.Addon()
def post(url,data,token=''):
    raw=json.dumps(data).encode('utf-8'); headers={'Content-Type':'application/json','User-Agent':'MKGA-Connector/0.1.0'}
    if token: headers['Authorization']='Bearer '+token
    req=urllib.request.Request(url,data=raw,headers=headers,method='POST')
    with urllib.request.urlopen(req,timeout=15) as r:return json.loads(r.read().decode('utf-8'))

def main():
    current=addon.getSetting('device_token')
    if current:
        if not xbmcgui.Dialog().yesno('MKGA Connector','This Kodi is already paired. Pair it to a different MKGA account/device slot?'):return
    code=xbmcgui.Dialog().numeric(0,'Enter the 6-digit code shown in MKGA.TV → Account → My Kodi')
    code=''.join(c for c in str(code or '') if c.isdigit())[:6]
    if len(code)!=6:return
    default_name=xbmc.getInfoLabel('System.FriendlyName') or platform.node() or 'Kodi device'
    name=xbmcgui.Dialog().input('Device name',defaultt=default_name,type=xbmcgui.INPUT_ALPHANUM)
    if not name:return
    try:
        result=post(API,{'code':code,'name':name,'platform':platform.system(),'kodiVersion':xbmc.getInfoLabel('System.BuildVersion')})
        addon.setSetting('device_id',str(result.get('deviceId','')));addon.setSetting('device_token',str(result.get('deviceToken','')));addon.setSetting('device_name',name)
        xbmcgui.Dialog().ok('MKGA Connector','Paired successfully. You can now install Stremio for Kodi from your MKGA.TV account.')
    except urllib.error.HTTPError as e:
        try: msg=json.loads(e.read().decode()).get('error','Pairing failed')
        except Exception: msg='Pairing failed'
        xbmcgui.Dialog().ok('MKGA Connector',msg)
    except Exception as e: xbmcgui.Dialog().ok('MKGA Connector','Could not reach MKGA.TV: '+str(e))
if __name__=='__main__':main()

import json, os, shutil, time, urllib.request, zipfile
import xbmc, xbmcaddon, xbmcvfs

BASE='https://mkga.tv/api/kodi/agent'
REPO_ZIP='https://raw.githubusercontent.com/0eroiQ/Stremio-for-Kodi/kodi-repository/repository.stremioforkodi/repository.stremioforkodi-1.1.0.zip'
ADDON_ID='script.stremioelec';REPO_ID='repository.stremioforkodi';CONNECTOR_ID='service.mkga.connector'
addon=xbmcaddon.Addon(); monitor=xbmc.Monitor()
def request(path,method='GET',data=None):
    token=addon.getSetting('device_token')
    if not token:return None
    headers={'Authorization':'Bearer '+token,'User-Agent':'MKGA-Connector/0.1.0'}; raw=None
    if data is not None:raw=json.dumps(data).encode();headers['Content-Type']='application/json'
    req=urllib.request.Request(BASE+path,data=raw,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=20) as r:return json.loads(r.read().decode())
def installed(addon_id):return xbmc.getCondVisibility('System.HasAddon(%s)'%addon_id)
def version():
    try:return xbmcaddon.Addon(ADDON_ID).getAddonInfo('version') if installed(ADDON_ID) else ''
    except Exception:return ''
def install_repo():
    home=xbmcvfs.translatePath('special://home/addons'); temp=xbmcvfs.translatePath('special://temp/mkga-repo.zip')
    urllib.request.urlretrieve(REPO_ZIP,temp)
    with zipfile.ZipFile(temp,'r') as z:
        roots={n.split('/')[0] for n in z.namelist() if n and not n.startswith('/')}
        if REPO_ID not in roots: raise Exception('Invalid repository package')
        for m in z.infolist():
            n=m.filename.replace('\\','/');parts=[p for p in n.split('/') if p]
            if not parts or parts[0]!=REPO_ID or '..' in parts:continue
            out=os.path.realpath(os.path.join(home,*parts));root=os.path.realpath(os.path.join(home,REPO_ID))
            if not (out==root or out.startswith(root+os.sep)):continue
            if m.is_dir():os.makedirs(out,exist_ok=True)
            else:
                os.makedirs(os.path.dirname(out),exist_ok=True)
                with z.open(m) as src,open(out,'wb') as dst:shutil.copyfileobj(src,dst)
    try:os.remove(temp)
    except Exception:pass
    xbmc.executebuiltin('UpdateLocalAddons');time.sleep(2);xbmc.executebuiltin('UpdateAddonRepos');time.sleep(4)
    return installed(REPO_ID)
def install_stremio():
    if not installed(REPO_ID) and not install_repo():raise Exception('Repository install failed')
    xbmc.executebuiltin('UpdateAddonRepos');time.sleep(4);xbmc.executebuiltin('InstallAddon(%s)'%ADDON_ID);time.sleep(6);xbmc.executebuiltin('UpdateLocalAddons');time.sleep(2)
    return installed(ADDON_ID)
def execute(action):
    if action=='install_repo':ok=install_repo();return ok,'Repository installed' if ok else 'Repository installation failed'
    if action in ('install_stremio','update_stremio'):
        ok=install_stremio();return ok,('Stremio for Kodi installed' if action=='install_stremio' else 'Stremio for Kodi update requested') if ok else 'Stremio for Kodi installation failed'
    if action=='repair_stremio':ok=install_repo() and install_stremio();return ok,'Repository and Stremio for Kodi repaired' if ok else 'Repair failed'
    return False,'Unknown command'
def state_payload(message=''):
    return {'message':message,'repoInstalled':installed(REPO_ID),'addonInstalled':installed(ADDON_ID),'addonVersion':version(),'connectorInstalled':installed(CONNECTOR_ID),'connectorVersion':addon.getAddonInfo('version')}
def report(cid,ok,message):
    try:request('/commands/'+cid+'/result','POST',dict(state_payload(message),ok=ok))
    except Exception:pass
def heartbeat():
    try:request('/heartbeat','POST',state_payload())
    except Exception:pass
next_heartbeat=0
while not monitor.abortRequested():
    if addon.getSetting('device_token'):
        try:
            if time.time()>=next_heartbeat:
                heartbeat();next_heartbeat=time.time()+30
            data=request('/commands') or {}
            for cmd in data.get('commands',[]):
                try:ok,msg=execute(str(cmd.get('action','')))
                except Exception as e:ok,msg=False,str(e)
                report(str(cmd.get('id','')),ok,msg)
        except Exception:pass
    if monitor.waitForAbort(10):break

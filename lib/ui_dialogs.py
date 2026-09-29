"""Theme-owned replacements for addon-created Kodi dialogs."""
from pathlib import Path
import threading
try:
    import xbmc
except ModuleNotFoundError:  # Unit-test/import environment outside Kodi.
    xbmc = None
try:
    import xbmcgui
except ModuleNotFoundError:
    class _WindowXMLDialog:
        pass
    class _DummyGUI:
        WindowXMLDialog = _WindowXMLDialog
        ListItem = type('ListItem', (), {})
    xbmcgui = _DummyGUI()
from lib.theme import window as themed_window
ROOT = str(Path(__file__).resolve().parents[1])
BACK = (10, 92, 216, 247)
_TOASTS = []
def _text(value): return str(value or '').replace('[CR]', '\n')

class MessageWindow(xbmcgui.WindowXMLDialog):
    def __init__(self,*args,**kwargs):
        self.title=_text(kwargs.pop('title','Stremio for Kodi')); self.message=_text(kwargs.pop('message',''))
        self.primary=_text(kwargs.pop('primary','OK')); self.secondary=kwargs.pop('secondary',None)
        self.result=False; self.autoclose=int(kwargs.pop('autoclose',0) or 0); super().__init__(*args,**kwargs)
    def onInit(self):
        self.setProperty('dialog_title',self.title); self.setProperty('dialog_message',self.message)
        self.setProperty('primary_label',self.primary); self.setProperty('secondary_label',_text(self.secondary or ''))
        self.setProperty('has_secondary','true' if self.secondary is not None else '')
        self.setFocusId(201 if self.secondary is None else 202)
        if self.autoclose>0: threading.Thread(target=self._timer,daemon=True).start()
    def _timer(self):
        if not xbmc.Monitor().waitForAbort(self.autoclose/1000.0):
            try:self.close()
            except Exception:pass
    def onClick(self,cid):
        if cid in (201,202): self.result=(cid==201); self.close()
    def onAction(self,action):
        if action.getId() in BACK:self.result=False;self.close()

class SelectWindow(xbmcgui.WindowXMLDialog):
    def __init__(self,*args,**kwargs):
        self.title=_text(kwargs.pop('title','Select')); self.labels=list(kwargs.pop('labels',()))
        self.multi=bool(kwargs.pop('multi',False)); self.preselect=kwargs.pop('preselect',None)
        self.result=None if self.multi else -1; super().__init__(*args,**kwargs)
    def _item(self,index):
        value=self.labels[index]; label=value.getLabel() if isinstance(value,xbmcgui.ListItem) else _text(value)
        item=xbmcgui.ListItem(label=label); item.setProperty('selected','✓' if index in self.selected else ''); return item
    def _render(self,focus=0):
        listing=self.getControl(600); listing.reset(); listing.addItems([self._item(i) for i in range(len(self.labels))])
        if self.labels:listing.selectItem(max(0,min(len(self.labels)-1,focus or 0)))
    def onInit(self):
        self.setProperty('dialog_title',self.title); self.setProperty('multiselect','true' if self.multi else '')
        if self.multi:
            self.selected=set(int(v) for v in (self.preselect or []) if isinstance(v,int) and 0<=v<len(self.labels))
            focus=min(self.selected) if self.selected else 0
        else:
            self.selected=set(); focus=self.preselect if isinstance(self.preselect,int) and self.preselect>=0 else 0
        self._render(focus); self.setFocusId(600)
    def onClick(self,cid):
        if cid==600:
            pos=self.getControl(600).getSelectedPosition()
            if self.multi:
                self.selected.remove(pos) if pos in self.selected else self.selected.add(pos); self._render(pos)
            else:self.result=pos;self.close()
        elif cid==201 and self.multi:self.result=sorted(self.selected);self.close()
        elif cid==202 and self.multi:self.result=None;self.close()
    def onAction(self,action):
        if action.getId() in BACK:self.result=None if self.multi else -1;self.close()

class TextWindow(xbmcgui.WindowXMLDialog):
    def __init__(self,*args,**kwargs):
        self.title=_text(kwargs.pop('title','Information'));self.body=_text(kwargs.pop('body',''));super().__init__(*args,**kwargs)
    def onInit(self):self.setProperty('dialog_title',self.title);self.setProperty('dialog_text',self.body);self.setFocusId(201)
    def onClick(self,cid):
        if cid==201:self.close()
    def onAction(self,action):
        if action.getId() in BACK:self.close()

class InputWindow(xbmcgui.WindowXMLDialog):
    LOWER=list('1234567890qwertyuiopasdfghjkl.zxcvbnm-_')
    UPPER=list('1234567890QWERTYUIOPASDFGHJKL.ZXCVBNM-_')
    SYMBOL=list('!@#$%^&*()/:;?=+,.[]{}<>\\|~_-')
    def __init__(self,*args,**kwargs):
        self.title=_text(kwargs.pop('title','Enter text'));self.value=_text(kwargs.pop('default',''))
        self.hidden=bool(kwargs.pop('hidden',False));self.numeric_only=bool(kwargs.pop('numeric_only',False))
        self.result='';self.mode=0;super().__init__(*args,**kwargs)
    def _display(self):self.setProperty('input_display',('•'*len(self.value)) if self.hidden else (self.value or ' '))
    def _keys(self):return list('1234567890.-') if self.numeric_only else (self.LOWER,self.UPPER,self.SYMBOL)[self.mode]
    def _render(self,focus=0):
        listing=self.getControl(600);listing.reset();rows=[]
        for value in self._keys():
            item=xbmcgui.ListItem(label=value);item.setProperty('value',value);rows.append(item)
        listing.addItems(rows)
        if rows:listing.selectItem(min(focus,len(rows)-1))
    def onInit(self):self.setProperty('dialog_title',self.title);self._display();self._render();self.setFocusId(600)
    def onClick(self,cid):
        if cid==600:
            item=self.getControl(600).getSelectedItem()
            if item:self.value+=item.getProperty('value');self._display()
        elif cid==201:self.mode=(self.mode+1)%3;self._render();self.setFocusId(600)
        elif cid==202:self.value+=' ';self._display()
        elif cid==203:self.value=self.value[:-1];self._display()
        elif cid==204:self.result=self.value;self.close()
        elif cid==205:self.result='';self.close()
    def onAction(self,action):
        if action.getId() in BACK:self.result='';self.close()

class ToastWindow(xbmcgui.WindowXMLDialog):
    def __init__(self,*args,**kwargs):
        self.title=_text(kwargs.pop('title','Stremio for Kodi'));self.message=_text(kwargs.pop('message',''));super().__init__(*args,**kwargs)
    def onInit(self):self.setProperty('dialog_title',self.title);self.setProperty('dialog_message',self.message)

class ProgressWindow(xbmcgui.WindowXMLDialog):
    def __init__(self,*args,**kwargs):
        self.cancelable=bool(kwargs.pop('cancelable',True));self.cancelled=False;super().__init__(*args,**kwargs)
    def onInit(self):
        self.setProperty('cancelable','true' if self.cancelable else '');self.setProperty('progress_percent','0')
        if self.cancelable:self.setFocusId(201)
    def onClick(self,cid):
        if cid==201 and self.cancelable:self.cancelled=True;self.close()
    def onAction(self,action):
        if action.getId() in BACK and self.cancelable:self.cancelled=True;self.close()

class DialogFacade:
    def _window(self,cls,filename,**kwargs):return themed_window(cls,filename,ROOT,'Main','1080i',**kwargs)
    def ok(self,heading,message,*lines):
        body='\n'.join([_text(message)]+[_text(v) for v in lines if v not in (None,'')])
        win=self._window(MessageWindow,'script-stremio-dialog-message.xml',title=heading,message=body,primary='OK')
        win.doModal();result=win.result;del win;return result
    def yesno(self,heading,message,nolabel='No',yeslabel='Yes',autoclose=0,defaultbutton=None):
        win=self._window(MessageWindow,'script-stremio-dialog-confirm.xml',title=heading,message=message,primary=yeslabel or 'Yes',secondary=nolabel or 'No',autoclose=autoclose)
        win.doModal();result=win.result;del win;return result
    def select(self,heading,labels,autoclose=0,preselect=-1,useDetails=False,**kwargs):
        win=self._window(SelectWindow,'script-stremio-dialog-select.xml',title=heading,labels=labels,multi=False,preselect=preselect)
        win.doModal();result=win.result;del win;return result
    def multiselect(self,heading,labels,autoclose=0,preselect=None,useDetails=False,**kwargs):
        win=self._window(SelectWindow,'script-stremio-dialog-select.xml',title=heading,labels=labels,multi=True,preselect=preselect)
        win.doModal();result=win.result;del win;return result
    def textviewer(self,heading,text,usemono=False):
        win=self._window(TextWindow,'script-stremio-dialog-text.xml',title=heading,body=text);win.doModal();del win;return True
    def input(self,heading,defaultt='',type=0,option=0,autoclose=0):
        hidden=type==getattr(xbmcgui,'INPUT_PASSWORD',-999) or option==getattr(xbmcgui,'ALPHANUM_HIDE_INPUT',-998)
        numeric=type in (getattr(xbmcgui,'INPUT_NUMERIC',-997),getattr(xbmcgui,'INPUT_IPADDRESS',-996))
        win=self._window(InputWindow,'script-stremio-dialog-input.xml',title=heading,default=defaultt,hidden=hidden,numeric_only=numeric)
        win.doModal();result=win.result;del win;return result
    def notification(self,heading,message,icon=None,time=5000,sound=True):
        win=self._window(ToastWindow,'script-stremio-dialog-toast.xml',title=heading,message=message);_TOASTS.append(win);win.show()
        def close_later():
            xbmc.Monitor().waitForAbort(max(0.5,float(time or 5000)/1000.0))
            try:win.close()
            except Exception:pass
            try:_TOASTS.remove(win)
            except ValueError:pass
        threading.Thread(target=close_later,daemon=True).start()

class ThemedProgress:
    def __init__(self,cancelable=True):self.cancelable=cancelable;self.window=None
    def create(self,heading,message=''):
        self.close();filename='script-stremio-dialog-progress.xml' if self.cancelable else 'script-stremio-dialog-progress-bg.xml'
        self.window=themed_window(ProgressWindow,filename,ROOT,'Main','1080i',cancelable=self.cancelable)
        self.window.setProperty('dialog_title',_text(heading));self.window.setProperty('dialog_message',_text(message));self.window.show()
    def update(self,percent=0,message='',*lines):
        if not self.window:return
        self.window.setProperty('progress_percent',str(max(0,min(100,int(percent or 0)))))
        if message or lines:self.window.setProperty('dialog_message','\n'.join([_text(message)]+[_text(v) for v in lines if v not in (None,'')]))
    def iscanceled(self):return bool(self.window and self.window.cancelled)
    def isCanceled(self):return self.iscanceled()
    def close(self):
        if self.window:
            try:self.window.close()
            except Exception:pass
            self.window=None

def _outside_kodi():
    try:
        import xbmcvfs  # noqa: F401
        return xbmc is None
    except ModuleNotFoundError:
        return True

def _current_gui():
    try:
        import importlib
        return importlib.import_module('xbmcgui')
    except ModuleNotFoundError:
        return xbmcgui

def dialog():
    gui = _current_gui()
    if _outside_kodi() and hasattr(gui, 'Dialog'):
        return gui.Dialog()
    return DialogFacade()

def progress():
    gui = _current_gui()
    if _outside_kodi() and hasattr(gui, 'DialogProgress'):
        return gui.DialogProgress()
    return ThemedProgress(True)

def progress_bg():
    gui = _current_gui()
    if _outside_kodi() and hasattr(gui, 'DialogProgressBG'):
        return gui.DialogProgressBG()
    return ThemedProgress(False)

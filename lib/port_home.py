"""Build the embedded Home from copied Nimbus XML; prints a patch payload.

The original menu List/ListItem, drawer, poster layouts, focus/glow animations
and geometry come from upstream/xml. Only content and window-global bindings
are adapted. Run outside Kodi; no files are written by this utility.
"""
from copy import deepcopy
from pathlib import Path
import json
import re
import xml.etree.ElementTree as E

ROOT = Path(__file__).resolve().parents[1] / 'resources/skins/Main'
SRC = ROOT / 'upstream/xml'
registry = {}
for path in SRC.glob('*.xml'):
    try:
        tree = E.parse(path).getroot()
    except E.ParseError:
        continue
    for node in tree.findall('include'):
        if node.get('name'):
            registry[node.get('name')] = node


def sub(value, params):
    return re.sub(r'\$PARAM\[([^]]+)\]', lambda m: params.get(m[1], ''), value or '')


def expand(name, supplied):
    source = registry[name]
    params = {p.get('name'): p.get('default', p.text or '') for p in source.findall('param')}
    params.update({k: v for k, v in supplied.items() if v != ''})
    definition = source.find('definition')
    source = definition if definition is not None else source
    result = []
    for child in source:
        if child.tag == 'param':
            continue
        node = deepcopy(child)
        for part in node.iter():
            part.text = sub(part.text, params)
            part.attrib = {k: sub(v, params) for k, v in part.attrib.items()}
        def walk(parent):
            for part in list(parent):
                if part.tag == 'include':
                    index = list(parent).index(part)
                    parent.remove(part)
                    if part.get('condition') == 'false':
                        continue
                    args = {p.get('name'): p.get('value', p.text or '') for p in part.findall('param')}
                    for offset, resolved in enumerate(expand(part.get('content') or part.text.strip(), args)):
                        parent.insert(index + offset, resolved)
                else:
                    walk(part)
        if node.tag == 'include':
            holder = E.Element('holder'); holder.append(node); walk(holder); result.extend(holder)
        else:
            walk(node); result.append(node)
    return result


def put(parent, tag, text, **attrs):
    node = E.SubElement(parent, tag, attrs); node.text = str(text); return node


def replace(parent, tag, text):
    for old in parent.findall(tag):
        parent.remove(old)
    return put(parent, tag, text)


home = E.parse(SRC / 'Home.xml').getroot()
oldpath = ROOT / '1080i/script-stremio-nimbus.xml'
old = oldpath.read_text()
previous = E.fromstring(old)
out = E.Element('window')
put(out, 'defaultcontrol', '9000', always='true')
controls = E.SubElement(out, 'controls')
# Reuse the already bound hero (same media-info geometry), with Home's x=50.
for node in list(previous.find('controls'))[:3]:
    copy = deepcopy(node)
    if copy.get('type') == 'group':
        replace(copy, 'left', '50')
        for animation in list(copy.findall('animation')):
            if animation.get('condition') == 'Control.HasFocus(9000)':
                copy.remove(animation)
        animation = E.SubElement(copy, 'animation', type='Conditional', condition='Control.HasFocus(9000)', reversible='true')
        put(animation, 'effect', '', type='slide', start='0,0', end='0,-540', time='500', tween='cubic', easing='inout')
        put(animation, 'effect', '', type='fade', start='100', end='0', time='650', tween='cubic', easing='in')
    controls.append(copy)
# Native Nimbus widget scroller. Original lists retain 230.5 x 393 layouts.
scroller = E.SubElement(controls, 'control', type='grouplist', id='2000')
for tag, value in [('left',0),('top',510),('width',1920),('height',570),('orientation','vertical'),('itemgap',0),('scrolltime',500)]:
    put(scroller,tag,value)
put(scroller,'animation','Conditional',effect='slide',end='490,0',time='500',tween='cubic',easing='inout',condition='Control.HasFocus(9000)')
template = registry['WidgetListPoster'].find('definition').find("control[@type='fixedlist']")
for cid in (400,401):
    group = E.SubElement(scroller,'control',type='group')
    put(group,'height',440)
    put(group,'visible','!String.IsEmpty(Window.Property(has%d))'%cid)
    for node in expand('CategoryLabel', {'list_id':str(cid),'label':'$INFO[Window.Property(row%d)]'%cid}):
        if cid == 400 and node.tag == 'control' and node.get('type') == 'group':
            replace(node, 'top', '120')
        for control in node.iter('control'):
            if control.get('type') == 'label':
                replace(control,'label','$INFO[Window.Property(row%d)]'%cid)
        group.append(node)
    listing = E.SubElement(group,'control',type='fixedlist',id=str(cid))
    for node in template:
        if node.tag in ('top','right','height','orientation','movement','itemlayout','focusedlayout'):
            listing.append(deepcopy(node))
    # Bring movies closer to the next heading; keep series artwork below the fold.
    replace(listing, 'top', '142' if cid == 400 else '122')
    for layout in list(listing):
        if layout.tag not in ('itemlayout','focusedlayout'):
            continue
        layout.attrib.pop('infoupdate',None)
        grp=layout.find('control')
        for inc in list(grp.findall('include')):
            grp.remove(inc)
        for node in expand('FlixWidgetMovieLayout', {'list_id':str(cid),'id':str(cid),'focused':'true' if layout.tag=='focusedlayout' else 'false'}):
            grp.append(node)
    for tag,value in [('onleft',9000),('onback',9000),('onup',9000 if cid==400 else 400),('ondown',401 if cid==400 else 9000),('onright',cid)]:
        put(listing,tag,value)
    put(listing,'scrolltime',700,tween='cubic',easing='out')

# Copy original Home menu group and List include, keeping dimensions and slide.
original_menu=home.find(".//control[@id='9000']")
drawer=E.SubElement(controls,'control',type='group')
put(drawer,'left',-540)
animation=E.SubElement(drawer,'animation',type='Conditional',condition='Control.HasFocus(9000)',reversible='true')
put(animation,'effect','',type='slide',start='0',end='540',time='500',tween='cubic',easing='inout')
drawer.extend(expand('MenuContentPanel',{'width':'549'}))
menu=E.SubElement(drawer,'control',type='fixedlist',id='9000')
for tag in ('left','top','width','height','movement','focusposition','scrolltime'):
    menu.append(deepcopy(original_menu.find(tag)))
for tag,val in [('onright',400),('onup',9000),('ondown',9000)]:
    put(menu,tag,val)
menu.extend(expand('List',{'id':'9000'}))
clock=E.SubElement(drawer,'control',type='label')
for tag,val in [('left',90),('top',900),('width',380),('height',55),('font','font37'),('textcolor','unfocused_text'),('label','$INFO[System.Time]')]: put(clock,tag,val)
date=E.SubElement(drawer,'control',type='label')
for tag,val in [('left',90),('top',950),('width',400),('height',40),('font','font23'),('textcolor','darkgrey'),('label','$INFO[System.Date]')]: put(date,tag,val)

variables={'MenuCaseVar':'$INFO[ListItem.Label]','MenuSelectorColor':'FFFFFFFF','MainMenuDiffuse':'FF121212',
           'FocusColorTheme':'FFFFFFFF','FocusedTextColorVar':'FFFFFFFF','BorderColorVar':'88FFFFFF',
           'FlixPosterVar':'$INFO[ListItem.Art(poster)]','IconWallThumbVar':'$INFO[ListItem.Art(thumb)]',
           'WallWatchedIconVar':'','HomescreenFlixCrumbs':'','SearchFlixCrumbs':'','FlixCrumbsVar':''}
expressions={k:'String.IsEqual(ListItem.Property(type),%s)'%v for k,v in [('isMovie','movie'),('isTVShow','series'),('isSeason','season'),('isEpisode','episode')]}
colors={'unfocused_text':'FFE5E5E5','darkgrey':'FFAAAAAA','grey':'FFAAAAAA','artwork_dim':'FFFFFFFF','text_shadow':'66000000'}
for node in out.iter():
    def adapt(value):
        value=re.sub(r'\$VAR\[([^]]+)\]',lambda m:variables.get(m[1],''),value or '')
        value=re.sub(r'\$EXP\[([^]]+)\]',lambda m:expressions.get(m[1],'false'),value)
        value=value.replace('white.png','colors/white.png') if value=='white.png' else value
        return colors.get(value,value)
    node.text=adapt(node.text)
    node.attrib={k:adapt(v) for k,v in node.attrib.items()}
    if node.tag in ('onfocus','onunfocus'):
        node.text='noop'
    if node.tag=='depth': node.text='0'
# Drop skin preference conditions from copied category labels: one native label.
for group in out.findall(".//control[@type='group']"):
    if group.get('id','').endswith('665'):
        for animation in list(group.findall('animation')):
            if 'Window(Home)' in animation.get('condition',''):
                group.remove(animation)
        labels=group.findall("control[@type='label']")
        for label in labels[:-1]: group.remove(label)
        if labels:
            for v in labels[-1].findall('visible'): labels[-1].remove(v)
            replace(labels[-1],'width','1815')
            replace(labels[-1],'height','40')
            replace(labels[-1],'top','0')
E.indent(out,space='  ')
new='<?xml version="1.0" encoding="UTF-8"?>\n'+E.tostring(out,encoding='unicode')+'\n'
assert '$PARAM[' not in new
print(json.dumps({'path':str(oldpath),'old':old,'new':new}))

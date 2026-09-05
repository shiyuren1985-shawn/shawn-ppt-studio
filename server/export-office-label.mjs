import { runProcess } from "./export-runtime.mjs";

export const PUBLIC_LABEL_ID = "937d27c0-b6cd-40f3-a0e1-631f68c80666";
export const PUBLIC_SITE_ID = "855b093e-7340-45c7-9f0c-96150415893e";

// The label source is a presentation that PowerPoint has already saved with the
// company Public label. We copy its complete MIP custom-properties part and
// verify the label id, tenant id, package relationship, content type and exact
// bytes. This preserves the real Office label metadata without opening or
// rewriting the user's generated deck in PowerPoint.
const PYTHON_PROGRAM = String.raw`
import hashlib, json, os, re, sys, tempfile, zipfile
from xml.etree import ElementTree as ET

CP='http://schemas.openxmlformats.org/officeDocument/2006/custom-properties'
REL='http://schemas.openxmlformats.org/package/2006/relationships'
CT='http://schemas.openxmlformats.org/package/2006/content-types'
CUSTOM_REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties'
CUSTOM_CT='application/vnd.openxmlformats-officedocument.custom-properties+xml'
CUSTOM_PART='docProps/custom.xml'
PATTERN=re.compile(r'^MSIP_Label_([0-9a-fA-F-]{36})_(.+)$')

def sha256(value):
    return hashlib.sha256(value).hexdigest()

def read_custom_part(pptx):
    try:
        with zipfile.ZipFile(pptx) as package:
            return package.read(CUSTOM_PART)
    except (KeyError, FileNotFoundError, zipfile.BadZipFile):
        raise RuntimeError('company sensitivity label template is unavailable')

def read_props(raw):
    root=ET.fromstring(raw)
    result={}
    for prop in root.findall('{%s}property' % CP):
        name=prop.attrib.get('name')
        child=next(iter(prop), None)
        if name and child is not None:
            result[name]=child.text or ''
    return result

def select_label(raw, expected_label_id):
    props=read_props(raw)
    grouped={}
    for name,value in props.items():
        match=PATTERN.match(name)
        if match:
            grouped.setdefault(match.group(1).lower(), {})[match.group(2)]=value
    enabled=[]
    for label_id, values in grouped.items():
        if values.get('Enabled','').lower()=='true' and values.get('SiteId'):
            enabled.append((label_id, values))
    if len(enabled)!=1:
        raise RuntimeError('sensitivity template must carry exactly one enabled company label')
    label_id, values=enabled[0]
    if expected_label_id and label_id.lower()!=expected_label_id.lower():
        raise RuntimeError('sensitivity template does not carry the required company label')
    return {
        'id':label_id,
        'site_id':values['SiteId'],
        'method':values.get('Method') or None,
        'property_count':sum(1 for name in props if name.startswith('MSIP_Label_')),
    }

def ensure_relationship(raw):
    root=ET.fromstring(raw)
    matches=[item for item in root if item.attrib.get('Type')==CUSTOM_REL]
    if len(matches)>1:
        raise RuntimeError('PPTX package has duplicate custom-properties relationships')
    if matches and (matches[0].attrib.get('Target')!='docProps/custom.xml' or matches[0].attrib.get('TargetMode')=='External'):
        raise RuntimeError('PPTX custom-properties relationship target is invalid')
    if not matches:
        used={item.attrib.get('Id') for item in root}
        number=1
        while 'rId%d' % number in used:
            number+=1
        ET.SubElement(root, '{%s}Relationship' % REL, {
            'Id':'rId%d' % number,
            'Type':CUSTOM_REL,
            'Target':'docProps/custom.xml',
        })
    ET.register_namespace('', REL)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)

def ensure_content_type(raw):
    root=ET.fromstring(raw)
    matches=[item for item in root if item.attrib.get('PartName')=='/docProps/custom.xml']
    if len(matches)>1:
        raise RuntimeError('PPTX package has duplicate custom-properties content types')
    if matches:
        if matches[0].attrib.get('ContentType')!=CUSTOM_CT:
            raise RuntimeError('PPTX custom-properties content type is invalid')
    else:
        ET.SubElement(root, '{%s}Override' % CT, {
            'PartName':'/docProps/custom.xml',
            'ContentType':CUSTOM_CT,
        })
    ET.register_namespace('', CT)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)

def rewrite(pptx, custom):
    folder=os.path.dirname(pptx)
    fd,tmp=tempfile.mkstemp(prefix='.label-part-',suffix='.pptx',dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(pptx,'r') as source, zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                if info.filename==CUSTOM_PART:
                    continue
                data=source.read(info.filename)
                if info.filename=='_rels/.rels':
                    data=ensure_relationship(data)
                elif info.filename=='[Content_Types].xml':
                    data=ensure_content_type(data)
                target.writestr(info,data)
            target.writestr(CUSTOM_PART,custom)
        os.replace(tmp,pptx)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def verify_package(pptx, expected_custom):
    with zipfile.ZipFile(pptx) as package:
        corrupt=package.testzip()
        if corrupt is not None:
            raise RuntimeError('labeled PPTX package is corrupt: '+corrupt)
        actual=package.read(CUSTOM_PART)
        if actual!=expected_custom:
            raise RuntimeError('sensitivity custom-properties part changed during assembly')
        relationships=ET.fromstring(package.read('_rels/.rels'))
        if len([item for item in relationships if item.attrib.get('Type')==CUSTOM_REL and item.attrib.get('Target')=='docProps/custom.xml' and item.attrib.get('TargetMode')!='External'])!=1:
            raise RuntimeError('sensitivity custom-properties relationship verification failed')
        content_types=ET.fromstring(package.read('[Content_Types].xml'))
        if len([item for item in content_types if item.attrib.get('PartName')=='/docProps/custom.xml' and item.attrib.get('ContentType')==CUSTOM_CT])!=1:
            raise RuntimeError('sensitivity custom-properties content type verification failed')
        return actual

request=json.load(sys.stdin)
source_custom=read_custom_part(request.get('source_pptx'))
label=select_label(source_custom,request.get('expected_label_id'))
rewrite(request['pptx_path'],source_custom)
actual=verify_package(request['pptx_path'],source_custom)
print(json.dumps({
    'id':label['id'],
    'name':'Public' if label['id'].lower()==request['public_label_id'].lower() else '项目标签',
    'site_id':label['site_id'],
    'method':label['method'],
    'source':'powerpoint_labeled_template',
    'package_part_preserved':True,
    'source_custom_xml_sha256':sha256(source_custom),
    'target_custom_xml_sha256':sha256(actual),
    'property_count':label['property_count'],
    'powerpoint_ui_verified':False,
},ensure_ascii=False))
`;

async function runPython(executable, input) {
  try {
    const result = await runProcess(executable, ["-c", PYTHON_PROGRAM], {
      input: JSON.stringify(input),
    });
    return JSON.parse(result.stdout);
  } catch (cause) {
    throw Object.assign(new Error(cause.message || "Office sensitivity label package copy failed", { cause }), {
      code: "office_label_failed",
    });
  }
}

export async function preserveOfficeLabelMetadata({
  pptxPath,
  sourcePptx,
  pythonPath,
  expectedLabelId = null,
}) {
  return runPython(pythonPath, {
    pptx_path: pptxPath,
    source_pptx: sourcePptx,
    expected_label_id: expectedLabelId,
    public_label_id: PUBLIC_LABEL_ID,
  });
}

export function verifyPreservedPublicLabel({ metadata } = {}) {
  if (!metadata || metadata.id?.toLowerCase() !== PUBLIC_LABEL_ID.toLowerCase()) {
    throw Object.assign(new Error("PPTX does not carry the required Public sensitivity label"), {
      code: "office_label_failed",
    });
  }
  if (metadata.site_id?.toLowerCase() !== PUBLIC_SITE_ID.toLowerCase()
    || metadata.package_part_preserved !== true
    || metadata.source_custom_xml_sha256 !== metadata.target_custom_xml_sha256
    || !Number.isInteger(metadata.property_count)
    || metadata.property_count < 4) {
    throw Object.assign(new Error("PPTX Public sensitivity label metadata was not preserved completely"), {
      code: "office_label_failed",
    });
  }
  return {
    verified: true,
    id: metadata.id,
    name: "Public",
    site_id: metadata.site_id,
    method: metadata.method,
    source: metadata.source,
    verification: "trusted_powerpoint_template_package",
  };
}

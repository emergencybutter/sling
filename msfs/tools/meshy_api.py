"""Generate a reference mesh with the Meshy API (multi-image to 3D) and download it as GLB.

    python meshy_api.py OUT.glb IMAGE [IMAGE ...]          (1-4 photos of the same part, .jpg / .png)

One image uses image-to-3d (remeshed to MESHY_POLYCOUNT triangles, default 100000), several multi-image-to-3d
(several views of the same object; mixing different aircraft or settings gives a blob).

The API key comes from MESHY_API_KEY, or from the file named by MESHY_API_KEY_FILE; it is never stored in the
project. Images are sent inline as data URIs. Untextured (we paint our own livery), so a run costs the base 30
credits. The task id and credits used are printed; the GLB then goes through tools/meshy_cowl.py / exterior.py.
"""
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.request

API = 'https://api.meshy.ai/openapi/v1'


def key():
    k = os.environ.get('MESHY_API_KEY')
    if not k and os.environ.get('MESHY_API_KEY_FILE'):
        with open(os.environ['MESHY_API_KEY_FILE']) as f:
            k = f.read().strip()
    if not k:
        sys.exit('set MESHY_API_KEY (or MESHY_API_KEY_FILE)')
    return k


def call(method, path, body=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Authorization': f'Bearer {key()}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode() or '{}')


def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or 'image/jpeg'
    with open(path, 'rb') as f:
        return f'data:{mime};base64,' + base64.b64encode(f.read()).decode()


def main():
    out, images = sys.argv[1], sys.argv[2:]
    if not 1 <= len(images) <= 4:
        sys.exit('give 1-4 images')
    print('balance before:', call('GET', '/balance').get('balance'))
    if len(images) == 1:
        kind, body = 'image-to-3d', {'image_url': data_uri(images[0]), 'should_remesh': True,
                                     'target_polycount': int(os.environ.get('MESHY_POLYCOUNT', 100000))}
    else:
        kind, body = 'multi-image-to-3d', {'image_urls': [data_uri(p) for p in images]}
    body.update({'should_texture': False, 'target_formats': ['glb']})
    task = call('POST', f'/{kind}', body)
    tid = task.get('result') or task.get('id')
    print(kind, 'task', tid, flush=True)
    while True:
        t = call('GET', f'/{kind}/{tid}')
        print(f"  {t.get('status')} {t.get('progress')}%", flush=True)
        if t.get('status') in ('SUCCEEDED', 'FAILED', 'CANCELED'):
            break
        time.sleep(15)
    if t.get('status') != 'SUCCEEDED':
        sys.exit(f"task {tid} {t.get('status')}: {t.get('task_error')}")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    urllib.request.urlretrieve(t['model_urls']['glb'], out)
    if t.get('thumbnail_url'):
        urllib.request.urlretrieve(t['thumbnail_url'], os.path.splitext(out)[0] + '_thumb.png')
    print('written', out, os.path.getsize(out), 'bytes; credits used', t.get('consumed_credits'),
          '; balance', call('GET', '/balance').get('balance'))


if __name__ == '__main__':
    main()

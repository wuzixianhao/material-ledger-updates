"""Public GitHub Releases updater. No ledger data or credentials are transmitted."""
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import uuid
from updater import version_tuple
from portable import VERSION

DEFAULT_REPOSITORY='wuzixianhao/material-ledger-updates'


def repository_name(value):
    value=value.strip().removesuffix('/').removesuffix('.git')
    if value.startswith('https://github.com/'):
        value=value[len('https://github.com/'):]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+',value) or value.split('/')[1] in ('.','..'):
        raise ValueError('请填写 GitHub 仓库地址或 用户名/仓库名。')
    return value


class GithubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        parsed=urllib.parse.urlsplit(newurl)
        if parsed.scheme!='https' or not github_host(parsed.hostname):
            raise ValueError('更新下载跳转到了不受支持的地址。')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def github_host(host):
    return host in ('github.com','api.github.com','objects.githubusercontent.com','release-assets.githubusercontent.com')


def request(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or not github_host(parsed.hostname) or parsed.username or parsed.password:
        raise ValueError('更新地址必须是 GitHub 的 HTTPS 地址。')
    req=urllib.request.Request(url,headers={'User-Agent':'MaterialLedger/'+VERSION,'Accept':'application/vnd.github+json'})
    return urllib.request.build_opener(GithubRedirect()).open(req,timeout=15)


def get_json(url):
    with request(url) as response:
        data=response.read(1_000_001)
    if len(data)>1_000_000:
        raise ValueError('版本信息过大。')
    return json.loads(data)


def check_release(repository,current_version=VERSION):
    repository=repository_name(repository)
    releases='https://github.com/'+repository+'/releases'
    meta=get_json(releases+'/latest/download/release.json')
    version=meta.get('version','')
    parsed=version_tuple(version)
    filename=f'MaterialLedger-{version}-Windows-x64.zip'
    if (meta.get('product')!='material-ledger' or meta.get('platform')!='windows-x64'
            or version!='.'.join(str(n) for n in parsed) or meta.get('filename')!=filename
            or not re.fullmatch('[a-f0-9]{64}',str(meta.get('sha256','')))
            or type(meta.get('size')) is not int or not 0<meta['size']<=100_000_000):
        raise ValueError('在线版本信息或更新包校验信息不完整。')
    if parsed<=version_tuple(current_version):
        return None
    return dict(meta,url=f'{releases}/download/v{version}/{filename}',notes=str(meta.get('notes') or '')[:3000])


def download_release(info,folder,progress=lambda n,total:None):
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    final=folder/(uuid.uuid4().hex+'.zip')
    part=final.with_suffix('.part')
    sha=hashlib.sha256()
    received=0
    try:
        with request(info['url']) as response,part.open('wb') as out:
            while True:
                chunk=response.read(128*1024)
                if not chunk:
                    break
                received+=len(chunk)
                if received>info['size']:
                    raise ValueError('下载文件大小与发布信息不一致。')
                sha.update(chunk)
                out.write(chunk)
                progress(received,info['size'])
        if received!=info['size'] or sha.hexdigest()!=info['sha256']:
            raise ValueError('下载不完整或校验失败，请重试。')
        part.replace(final)
        return final
    finally:
        part.unlink(missing_ok=True)


def load_settings(base):
    try:
        settings=json.loads((Path(base)/'online-update-settings.json').read_text(encoding='utf-8'))
        return dict(repository=repository_name(settings['repository']),automatic=bool(settings.get('automatic',True)))
    except (OSError,ValueError,KeyError,TypeError):
        return dict(repository=DEFAULT_REPOSITORY,automatic=True)


def save_settings(base,repository,automatic):
    settings=dict(repository=repository_name(repository),automatic=bool(automatic))
    path=Path(base)/'online-update-settings.json'
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)

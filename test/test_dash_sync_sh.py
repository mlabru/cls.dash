"""
test_dash_sync_sh

testes do dash_sync.sh (host de exibição puxa os produtos do host de cálculo).

O script roda numa cópia em tmp_path (com dsh_common.sh e cls_common.sh), então
data/run e logs/ ficam no tmp.  O ssh é falso: descarta as opções e o host e
roda o comando "remoto" localmente, de modo que o rsync é o real (mtime,
exclusões e padrões testados de verdade).  Um rsync de fachada na frente do
real registra os argumentos e falha quando FAKE_RSYNC_FAIL aparece neles.

2026.nov  mlabru  initial version
"""
# python library
import fcntl
import os
import shutil
import subprocess
from pathlib import Path

# pytest
import pytest

# < constantes >-------------------------------------------------------------------------

CPTH_REPO = Path(__file__).resolve().parent.parent
CS_REAL_RSYNC = shutil.which("rsync")

pytestmark = pytest.mark.skipif(CS_REAL_RSYNC is None or shutil.which("flock") is None,
                                reason="rsync/flock indisponíveis")

CS_FAKE_SSH = """#!/usr/bin/env bash
# ssh falso: ignora as opções e o host e roda o comando localmente
while [ $# -gt 0 ]; do
    case "$1" in
        -o|-i) shift 2 ;;
        -*)    shift ;;
        *)     break ;;
    esac
done
shift   # host
exec sh -c "$*"
"""

CS_FAKE_RSYNC = """#!/usr/bin/env bash
# rsync de fachada: registra a chamada e falha se FAKE_RSYNC_FAIL estiver nos
# argumentos; senão, delega ao rsync real
echo "$*" >> "${FAKE_RSYNC_CALLS}"
if [ -n "${FAKE_RSYNC_FAIL:-}" ] && [[ "$*" == *"${FAKE_RSYNC_FAIL}"* ]]; then
    echo "falha simulada" >&2
    exit 23
fi
exec %s "$@"
"""


# < fixtures >---------------------------------------------------------------------------

@pytest.fixture
def sandbox(tmp_path):
    """cópia do script, ssh/rsync falsos no PATH, árvore remota e ambiente"""
    l_repo = tmp_path / "repo"
    l_repo.mkdir()

    for ls_name in ("dash_sync.sh", "dsh_common.sh", "cls_common.sh"):
        # resolve o symlink do cls_common.sh
        shutil.copy((CPTH_REPO / ls_name).resolve(), l_repo / ls_name)

    l_bin = tmp_path / "bin"
    l_bin.mkdir()
    (l_bin / "ssh").write_text(CS_FAKE_SSH)
    (l_bin / "rsync").write_text(CS_FAKE_RSYNC % CS_REAL_RSYNC)
    for l_file in l_bin.iterdir():
        l_file.chmod(0o755)

    l_remote = tmp_path / "remote"
    l_local = tmp_path / "local"

    ldct_env = {k: v for k, v in os.environ.items()
                if not k.startswith(("DASH_SYNC_", "FAKE_RSYNC_"))
                and k not in ("STSC_DATA", "OFLOW_DATA", "UNET_DATA", "RSM_PATH")}
    ldct_env.update({
        "PATH": f"{l_bin}:{ldct_env.get('PATH', '/usr/bin:/bin')}",
        "HOME": str(tmp_path),
        "DASH_SYNC_HOST": "calc",
        "DASH_SYNC_REMOTE_ROOT": str(l_remote),
        "STSC_DATA": str(l_local),
        "RSM_PATH": str(l_local / "mrad"),
        "FAKE_RSYNC_CALLS": str(tmp_path / "calls.txt"),
    })

    return {"repo": l_repo, "remote": l_remote, "local": l_local,
            "calls": tmp_path / "calls.txt", "env": ldct_env}


def _write(fpth_file: Path, fs_text: str, fi_mtime: int | None = None) -> Path:
    """cria um arquivo (e os diretórios), opcionalmente com mtime fixo"""
    fpth_file.parent.mkdir(parents=True, exist_ok=True)
    fpth_file.write_text(fs_text)
    if fi_mtime is not None:
        os.utime(fpth_file, (fi_mtime, fi_mtime))
    return fpth_file


def _run(fdct_box: dict, **fdct_env) -> subprocess.CompletedProcess:
    """roda o dash_sync.sh da cópia"""
    ldct_env = dict(fdct_box["env"], **fdct_env)
    return subprocess.run(["bash", str(fdct_box["repo"] / "dash_sync.sh")],
                          env=ldct_env, capture_output=True, text=True, timeout=60)


def _calls(fdct_box: dict) -> list[str]:
    """chamadas locais registradas pelo rsync de fachada (sem o lado "remoto",
    o rsync --server que o ssh falso também roda por aqui)"""
    lpth = fdct_box["calls"]
    if not lpth.exists():
        return []
    return [ls for ls in lpth.read_text().splitlines() if not ls.startswith("--server")]


# < testes >-----------------------------------------------------------------------------

def test_copia_so_os_padroes_e_preserva_mtime(sandbox):
    l_remote, l_local = sandbox["remote"], sandbox["local"]
    li_mtime = 1_700_000_000

    _write(l_remote / "oflw/data/output/CGU_400_now_mosaico.gif", "gif", li_mtime)
    _write(l_remote / "oflw/data/output/CGU_400_verify.jsonl", "jsonl")
    _write(l_remote / "oflw/data/output/.CGU_400_now.gif.tmp", "parcial")
    _write(l_remote / "oflw/data/assets/no_cast.png", "png")
    _write(l_remote / "oflw/data/assets/mapa.shp", "shp")
    _write(l_remote / "unet/data/output/STI_400_now_mosaico.gif", "gif")
    _write(l_remote / "unet/data/output/STI_400_monitor.json", "json")
    _write(l_remote / "mrad/data/temp/rsm_temp.json", "{}")
    _write(l_remote / "mrad/data/temp/outro.txt", "x")
    _write(l_remote / "mrad/data/output/rsm_out.png", "png")

    l_res = _run(sandbox)
    assert l_res.returncode == 0, l_res.stderr

    l_gif = l_local / "oflw/data/output/CGU_400_now_mosaico.gif"
    assert l_gif.read_text() == "gif"
    assert int(l_gif.stat().st_mtime) == li_mtime
    assert not (l_local / "oflw/data/output/CGU_400_verify.jsonl").exists()
    assert not (l_local / "oflw/data/output/.CGU_400_now.gif.tmp").exists()

    assert (l_local / "oflw/data/assets/no_cast.png").exists()
    assert not (l_local / "oflw/data/assets/mapa.shp").exists()

    assert (l_local / "unet/data/output/STI_400_now_mosaico.gif").exists()
    assert not (l_local / "unet/data/output/STI_400_monitor.json").exists()

    assert (l_local / "mrad/data/temp/rsm_temp.json").exists()
    assert not (l_local / "mrad/data/temp/outro.txt").exists()
    assert (l_local / "mrad/data/output/rsm_out.png").exists()


def test_argumentos_do_rsync(sandbox):
    _run(sandbox, DASH_SYNC_SSH_KEY="/chave/id_dash")

    llst_calls = _calls(sandbox)
    assert len(llst_calls) == 5
    for ls_call in llst_calls:
        assert "--delay-updates" in ls_call
        assert "--exclude=.*" in ls_call
        assert "ssh -o BatchMode=yes -i /chave/id_dash" in ls_call
        assert f"calc:{sandbox['remote']}/" in ls_call


def test_raiz_remota_vazia_usa_caminho_relativo(sandbox):
    # com rrsync -ro a raiz é a do lado remoto: origem sem prefixo
    _run(sandbox, DASH_SYNC_REMOTE_ROOT="")
    assert "calc:oflw/data/output/" in _calls(sandbox)[0]


def test_sem_host_e_erro(sandbox):
    l_res = _run(sandbox, DASH_SYNC_HOST="")

    assert l_res.returncode == 1
    assert "DASH_SYNC_HOST" in l_res.stderr
    assert _calls(sandbox) == []


def test_falha_de_um_par_nao_impede_os_outros(sandbox):
    _write(sandbox["remote"] / "unet/data/output/STI_400_now_mosaico.gif", "gif")

    l_res = _run(sandbox, FAKE_RSYNC_FAIL="oflw/data/output")

    assert l_res.returncode == 1
    assert len(_calls(sandbox)) == 5
    assert (sandbox["local"] / "unet/data/output/STI_400_now_mosaico.gif").exists()
    assert "[warn]" in l_res.stderr and "oflw/data/output" in l_res.stderr
    assert "falha simulada" in (sandbox["repo"] / "logs/dash_sync.err").read_text()


def test_lock_ocupado_sai_com_zero(sandbox):
    l_lock = sandbox["repo"] / "data/run/.dash_sync.lock"
    l_lock.parent.mkdir(parents=True)

    with open(l_lock, "w") as l_fd:
        fcntl.flock(l_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        l_res = _run(sandbox)

    assert l_res.returncode == 0
    assert "já em execução" in l_res.stderr
    assert _calls(sandbox) == []

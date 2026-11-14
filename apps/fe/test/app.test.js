"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");

const APP_JS_PATH = require.resolve("../app.js");

const BASE_HTML =
    '<!doctype html><body>' +
    '<span id="page-title"></span>' +
    '<div id="dashboard"></div>' +
    '<div id="progress-fill"></div>' +
    '</body>';

// carrega app.js "do zero" a cada teste: o módulo guarda estado próprio
// (config, currentPage, timers) em variáveis de módulo, então precisamos
// de uma instância nova de document/window e limpar o require cache.
function loadApp() {
    const dom = new JSDOM(BASE_HTML);

    global.document = dom.window.document;
    global.window = dom.window;

    delete require.cache[APP_JS_PATH];

    return require("../app.js");
}

test.afterEach(() => {
    delete global.fetch;
    delete require.cache[APP_JS_PATH];
});

// ---------------------------------------------------------------------
// applyGrid
// ---------------------------------------------------------------------

test("applyGrid: 1 tile -> uma coluna, uma linha", () => {
    const dash = loadApp();
    dash.applyGrid(1);

    const dashboard = global.document.getElementById("dashboard");
    assert.equal(dashboard.style.gridTemplateColumns, "1fr");
    assert.equal(dashboard.style.gridTemplateRows, "1fr");
});

test("applyGrid: 2 tiles -> duas colunas, uma linha", () => {
    const dash = loadApp();
    dash.applyGrid(2);

    const dashboard = global.document.getElementById("dashboard");
    assert.equal(dashboard.style.gridTemplateColumns, "1fr 1fr");
    assert.equal(dashboard.style.gridTemplateRows, "1fr");
});

test("applyGrid: 3 ou mais tiles -> grade 2x2", () => {
    const dash = loadApp();
    dash.applyGrid(3);

    const dashboard = global.document.getElementById("dashboard");
    assert.equal(dashboard.style.gridTemplateColumns, "1fr 1fr");
    assert.equal(dashboard.style.gridTemplateRows, "1fr 1fr");
});

test("applyGrid: respeita o limite MAX_TILES mesmo com contagem maior", () => {
    const dash = loadApp();
    dash.applyGrid(10); // deve se comportar como 3 (o cap é interno à função)

    const dashboard = global.document.getElementById("dashboard");
    assert.equal(dashboard.style.gridTemplateColumns, "1fr 1fr");
    assert.equal(dashboard.style.gridTemplateRows, "1fr 1fr");
});

// ---------------------------------------------------------------------
// createTileMedia
// ---------------------------------------------------------------------

test("createTileMedia: tile de imagem gera <img> com a URL correta", () => {
    const dash = loadApp();
    const container = global.document.createElement("div");

    const el = dash.createTileMedia({ type: "image", file: "monrad.png" }, container);

    assert.equal(el.tagName, "IMG");
    assert.match(el.src, /\/media\/monrad\.png\?t=\d+$/);
});

test("createTileMedia: tile 'gif' também gera <img>", () => {
    const dash = loadApp();
    const container = global.document.createElement("div");

    const el = dash.createTileMedia({ type: "gif", file: "slm_out.gif" }, container);

    assert.equal(el.tagName, "IMG");
});

test("createTileMedia: tile de vídeo gera <video> em loop, mudo e autoplay", () => {
    const dash = loadApp();
    const container = global.document.createElement("div");

    const el = dash.createTileMedia({ type: "video", file: "goes1913.mp4" }, container);

    assert.equal(el.tagName, "VIDEO");
    assert.equal(el.autoplay, true);
    assert.equal(el.loop, true);
    assert.equal(el.muted, true);
    assert.match(el.src, /\/media\/goes1913\.mp4\?t=\d+$/);
});

test("createTileMedia: tipo desconhecido retorna null", () => {
    const dash = loadApp();
    const container = global.document.createElement("div");

    const el = dash.createTileMedia({ type: "pdf", file: "x.pdf" }, container);

    assert.equal(el, null);
});

// ---------------------------------------------------------------------
// createTile
// ---------------------------------------------------------------------

test("createTile: exibe cabeçalho apenas quando o tile tem título", () => {
    const dash = loadApp();

    const withTitle = dash.createTile({ type: "image", file: "a.png", title: "Radar" });
    assert.equal(withTitle.querySelector(".tile-header").textContent, "Radar");

    const withoutTitle = dash.createTile({ type: "image", file: "b.png" });
    assert.equal(withoutTitle.querySelector(".tile-header"), null);
});

test("createTile: rodapé mostra a data quando file_modified está presente", () => {
    const dash = loadApp();

    const tile = dash.createTile({ type: "image", file: "a.png", file_modified: "01/01/2026 10:00" });
    assert.equal(tile.querySelector(".tile-footer").textContent, "Última atualização em 01/01/2026 10:00");
});

test("createTile: rodapé indica indisponibilidade sem file_modified", () => {
    const dash = loadApp();

    const tile = dash.createTile({ type: "image", file: "a.png" });
    assert.equal(tile.querySelector(".tile-footer").textContent, "Data de modificação indisponível");
});

// ---------------------------------------------------------------------
// loadConfig
// ---------------------------------------------------------------------

function withFakeSetTimeout(fn) {
    const scheduled = [];
    const original = global.setTimeout;
    global.setTimeout = (cb, ms) => {
        scheduled.push({ cb, ms });
        return 0;
    };

    return fn(scheduled).finally(() => {
        global.setTimeout = original;
    });
}

test("loadConfig: sucesso agenda o refresh periódico com refresh_seconds*1000", async () => {
    const dash = loadApp();

    global.fetch = async () => ({
        ok: true,
        json: async () => ({
            refresh_seconds: 30,
            pages: [{ name: "P1", duration: 5, tiles: [{ type: "image", file: "a.png" }] }],
        }),
    });

    await withFakeSetTimeout(async (scheduled) => {
        await dash.loadConfig();
        assert.ok(scheduled.some((t) => t.ms === 30000));
    });
});

test("loadConfig: resposta HTTP não-ok agenda nova tentativa em 5s", async () => {
    const dash = loadApp();

    global.fetch = async () => ({ ok: false, status: 500 });

    await withFakeSetTimeout(async (scheduled) => {
        await dash.loadConfig();
        assert.deepEqual(
            scheduled.map((t) => t.ms),
            [5000],
        );
    });
});

test("loadConfig: falha de rede agenda nova tentativa em 5s", async () => {
    const dash = loadApp();

    global.fetch = async () => {
        throw new Error("network down");
    };

    await withFakeSetTimeout(async (scheduled) => {
        await dash.loadConfig();
        assert.deepEqual(
            scheduled.map((t) => t.ms),
            [5000],
        );
    });
});

// ---------------------------------------------------------------------
// layout "rows" (nowcast) e imagem de indisponível
// ---------------------------------------------------------------------

test("applyGrid: layout 'rows' -> uma coluna e uma linha por tile, sem limite", () => {
    const dash = loadApp();
    dash.applyGrid(4, "rows");

    const dashboard = document.getElementById("dashboard");
    assert.equal(dashboard.style.gridTemplateColumns, "1fr");
    assert.equal(dashboard.style.gridTemplateRows, "repeat(4, 1fr)");
});

test("renderPage: página 'rows' não corta os tiles em MAX_TILES", () => {
    const dash = loadApp();
    const tile = (n) => ({ type: "gif", file: `nowcast/R${n}_400_now_mosaico.gif`, title: `R${n}` });

    dash.renderPage({ duration: 10, layout: "rows", tiles: [tile(1), tile(2), tile(3), tile(4)] });

    assert.equal(document.querySelectorAll("#dashboard .tile").length, 4);
});

test("renderPage: página comum continua limitada a MAX_TILES", () => {
    const dash = loadApp();
    const tile = { type: "image", file: "a.png" };

    dash.renderPage({ duration: 10, tiles: [tile, tile, tile, tile] });

    assert.equal(document.querySelectorAll("#dashboard .tile").length, 3);
});

test("showTileError: troca a mídia pela imagem de indisponível e mantém o título", () => {
    const dash = loadApp();
    const tileElement = dash.createTile({ type: "gif", file: "x.gif", title: "Radar X" });

    dash.showTileError(tileElement, "x.gif");

    const img = tileElement.querySelector(".tile-media img");
    assert.ok(img.src.endsWith("/media/_unavailable"));
    assert.equal(tileElement.querySelector(".tile-header").textContent, "Radar X");
    assert.equal(tileElement.querySelector(".tile-footer").textContent, "Arquivo não encontrado: x.gif");
    assert.ok(!tileElement.classList.contains("tile--error"));
});

test("showTileError: se a imagem de indisponível também falhar, vira texto de erro", () => {
    const dash = loadApp();
    const tileElement = dash.createTile({ type: "gif", file: "x.gif" });

    dash.showTileError(tileElement, "x.gif");
    tileElement.querySelector(".tile-media img").onerror();

    assert.ok(tileElement.classList.contains("tile--error"));
    assert.equal(tileElement.textContent, "Arquivo não encontrado: x.gif");
});

// ---------------------------------------------------------------------
// URL versionada, endereço do backend, aviso e alerta prioritário
// ---------------------------------------------------------------------

test("buildMediaUrl: com file_version usa ?v= (URL estável)", () => {
    const dash = loadApp();

    assert.equal(dash.buildMediaUrl("a.gif", 1700000000), "http://localhost:8000/media/a.gif?v=1700000000");
    assert.match(dash.buildMediaUrl("a.gif"), /\/media\/a\.gif\?t=\d+$/);
});

test("createTileMedia: passa file_version para a URL", () => {
    const dash = loadApp();
    const tileElement = document.createElement("div");

    const img = dash.createTileMedia({ type: "gif", file: "x.gif", file_version: 42 }, tileElement);

    assert.ok(img.src.endsWith("/media/x.gif?v=42"));
});

test("resolveApiBase: DASH_API_BASE tem prioridade (sem barra no fim)", () => {
    const dash = loadApp();
    window.DASH_API_BASE = "http://servidor:9000/";

    assert.equal(dash.resolveApiBase(), "http://servidor:9000");
});

test("resolveApiBase: página http usa o host da página na porta 8000", () => {
    const dom = new JSDOM(BASE_HTML, { url: "http://videowall.local:8080/index.html" });
    global.window = dom.window;
    global.document = dom.window.document;
    delete require.cache[APP_JS_PATH];
    const dash = require("../app.js");

    assert.equal(dash.resolveApiBase(), "http://videowall.local:8000");
});

test("resolveApiBase: fora de http(s) cai em localhost:8000", () => {
    const dash = loadApp();  // jsdom em about:blank

    assert.equal(dash.resolveApiBase(), "http://localhost:8000");
});

function loadAppWithNotice() {
    const dash = loadApp();
    const notice = document.createElement("span");
    notice.id = "page-notice";
    document.body.appendChild(notice);
    return dash;
}

test("updateTitle: escreve o aviso da página em #page-notice", async () => {
    const dash = loadAppWithNotice();

    await withFakeSetTimeout(async (scheduled) => {
        dash.updateTitle({ name: "Nowcast", notice: "Sem atualização: Santiago (STI)" });
        scheduled.forEach((t) => t.cb());
    });

    assert.equal(document.getElementById("page-title").textContent, "Nowcast");
    assert.equal(document.getElementById("page-notice").textContent, "Sem atualização: Santiago (STI)");

    await withFakeSetTimeout(async (scheduled) => {
        dash.updateTitle({ name: "Outra" });
        scheduled.forEach((t) => t.cb());
    });

    assert.equal(document.getElementById("page-notice").textContent, "");
});

const ALERT_CONFIG = {
    refresh_seconds: 30,
    pages: [
        { name: "P0", duration: 5, tiles: [] },
        { name: "P1", duration: 5, tiles: [] },
    ],
};

function fakeFetch(alert) {
    return async (url) => ({
        ok: true,
        json: async () => (url.endsWith("/api/state") ? { alert } : ALERT_CONFIG),
    });
}

test("pollState: alerta ativo vai para a página 0, fica presa e pinta o body", async () => {
    const dash = loadApp();

    await withFakeSetTimeout(async (scheduled) => {
        global.fetch = fakeFetch(false);
        await dash.loadConfig();
        dash.showPage(1);
        scheduled.length = 0;

        global.fetch = fakeFetch(true);
        await dash.pollState();

        assert.ok(document.body.classList.contains("alert"));
        // só o fade e a próxima consulta: nenhuma troca de página agendada
        assert.deepEqual(scheduled.map((t) => t.ms).sort((a, b) => a - b), [300, 300, 1000]);
        scheduled.forEach((t) => { if (t.ms === 300) t.cb(); });
    });

    assert.equal(document.getElementById("page-title").textContent, "⚠️ ALERTA DE TEMPO SEVERO ATIVO ⚠️");
});

test("pollState: fim do alerta tira a classe e volta a agendar a rotação", async () => {
    const dash = loadApp();

    await withFakeSetTimeout(async (scheduled) => {
        global.fetch = fakeFetch(true);
        await dash.loadConfig();
        await dash.pollState();
        scheduled.length = 0;

        global.fetch = fakeFetch(false);
        await dash.pollState();

        assert.ok(!document.body.classList.contains("alert"));
        assert.ok(scheduled.some((t) => t.ms === 5000));
    });
});

test("pollState: falha de rede mantém o estado e agenda nova consulta", async () => {
    const dash = loadApp();

    await withFakeSetTimeout(async (scheduled) => {
        global.fetch = async () => { throw new Error("down"); };
        await dash.pollState();

        assert.ok(!document.body.classList.contains("alert"));
        assert.deepEqual(scheduled.map((t) => t.ms), [1000]);
    });
});

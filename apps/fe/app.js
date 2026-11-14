// ------------------------------------------------------------------------------------
// Centro Logístico de Simulação Meteorológica
// Copyright (c) 1995-2026, Instituto de Controle do Espaço Aéreo
//
// app.js
// frontend do dashboard web: busca a configuração no backend (apps/be) e
// mostra as páginas em ciclo, cada uma com até MAX_TILES tiles. Páginas
// com layout "rows" (nowcast: o backend já as expandiu, uma por radar, com
// os mosaicos do 25.oflow e do 25.u-net) mostram um tile por linha, sem o
// limite MAX_TILES.
//
// workflow:
//   1. loadConfig: busca /api/config; se falhar, tenta de novo a cada
//      RETRY_INTERVAL_MS até conseguir;
//   2. startDashboard -> showPage(0);
//   3. showPage: fade-out, troca os tiles, fade-in, barra de progresso, e
//      agenda a próxima página para daqui a page.duration segundos;
//   4. em paralelo, scheduleConfigRefresh busca a configuração de novo a
//      cada refresh_seconds (a próxima página já usa a versão nova);
//   5. em paralelo, pollState consulta /api/state a cada STATE_POLL_MS:
//      com o alerta prioritário ativo, a tela fica presa na página
//      ALERT_PAGE_INDEX com o cabeçalho vermelho (como no dashboard desktop).
//
// endereço do backend: resolveApiBase (window.DASH_API_BASE, se definido
// antes deste script; senão o host da página na porta API_PORT).
//
// elementos do index.html usados aqui: #page-title, #page-notice,
// #dashboard, #progress-fill. Classes CSS usadas (style.css): "visible",
// "dashboard--visible", "tile", "tile-header", "tile-media", "tile-footer",
// "tile--error", "tile--unavailable", e "alert" no <body>.
//
// mídia que não carrega: o tile mostra a imagem de "indisponível" do
// backend (UNAVAILABLE_URL, o no_cast.png do 25.oflow); só se ela também
// falhar o tile vira texto de erro.
//
// 2026.nov  mlabru  showPage normaliza o índice (o número de páginas muda a
//                   cada refresh; sair do alerta com currentPage fora da
//                   faixa parava a rotação) e cancela fades pendentes
//
// 2026.out  mlabru  endereço do backend derivado da página (resolveApiBase);
//                   URL da mídia versionada pelo mtime (?v=); aviso dos
//                   radares ocultos no cabeçalho; alerta prioritário
//                   (/api/state)
//
// 2026.out  mlabru  páginas "rows" (nowcast, uma linha por radar); mídia
//                   com erro mostra a imagem de indisponível do backend
//
// 2026.out  mlabru  refatoração para legibilidade: createTileMedia dividido
//                   (imagem / vídeo / erro); showPage dividido (renderPage,
//                   scheduleNextPage); os 300 ms do fade viraram a constante
//                   FADE_DURATION_MS; JSDoc em todas as funções
//
// 2025.nov  mlabru  initial version (Linux/JS)

"use strict";

// < CONSTANTES >----------------------------------------------------------------------

// porta do backend (apps/be, PORT no .env), no mesmo host da página
const API_PORT = 8000;

// endereço do backend (ver resolveApiBase)
const API_BASE = resolveApiBase();

const API_URL = `${API_BASE}/api/config`;
const STATE_URL = `${API_BASE}/api/state`;
const MEDIA_URL = `${API_BASE}/media`;

// imagem de "indisponível" servida pelo backend (OFL_NO_CAST_IMAGE)
const UNAVAILABLE_URL = `${MEDIA_URL}/_unavailable`;

// espera entre tentativas quando o backend não responde
const RETRY_INTERVAL_MS = 5000;

// usado quando o config.json não define refresh_seconds
const DEFAULT_REFRESH_SECONDS = 60;

// máximo de tiles por página (os excedentes são ignorados)
const MAX_TILES = 3;

// precisa bater com a duração da transição de opacidade em style.css
const FADE_DURATION_MS = 300;

// intervalo da consulta ao estado do alerta prioritário
const STATE_POLL_MS = 1000;

// página exibida durante o alerta prioritário e texto do cabeçalho
const ALERT_PAGE_INDEX = 0;
const ALERT_TITLE = "⚠️ ALERTA DE TEMPO SEVERO ATIVO ⚠️";

// < ESTADO >--------------------------------------------------------------------------

let config = null;         // última configuração recebida do backend
let currentPage = 0;       // índice da página na tela, em config.pages
let pageTimer = null;      // timer que troca para a próxima página
let configTimer = null;    // timer da próxima atualização da configuração
let renderTimer = null;    // fim do fade-out: troca os tiles (ver showPage)
let titleTimer = null;     // fim do fade-out do título (ver updateTitle)
let inAlert = false;       // alerta prioritário ativo (ver pollState)

// < ENDEREÇO DO BACKEND >-------------------------------------------------------------

// ------------------------------------------------------------------------------------
// endereço base do backend:
//   1. window.DASH_API_BASE, se a página o definir antes de carregar este
//      script (ex.: backend em outra máquina);
//   2. senão, se a página veio por http(s): mesmo host, porta API_PORT;
//   3. senão (file://, testes no Node): http://localhost:API_PORT.
// O CORS_ORIGINS do backend continua precisando aceitar a origem da página.
//
// @returns {string} ex.: "http://videowall:8000" (sem barra no fim)
//
function resolveApiBase() {

    const win = typeof window === "undefined" ? undefined : window;

    if (win && win.DASH_API_BASE) {
        return String(win.DASH_API_BASE).replace(/\/+$/, "");
    }

    const location = win && win.location;

    if (location && (location.protocol === "http:" || location.protocol === "https:")) {
        return `${location.protocol}//${location.hostname}:${API_PORT}`;
    }

    return `http://localhost:${API_PORT}`;

} /* resolveApiBase */

// < CONFIGURAÇÃO >--------------------------------------------------------------------

// ------------------------------------------------------------------------------------
// busca a configuração no backend.
// 
// @returns {Promise<object>} a configuração (pages, refresh_seconds, ...)
// @throws {Error} se a resposta HTTP não for 2xx ou a rede falhar
//
async function fetchConfig() {

    const response = await fetch(API_URL);

    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }

    return response.json();

} /* fetchConfig */

// ------------------------------------------------------------------------------------
// primeira carga da configuração. Em caso de sucesso, inicia o dashboard e
// o refresh periódico; em caso de falha, agenda nova tentativa em
// RETRY_INTERVAL_MS (sem iniciar nada).
// 
// @returns {Promise<void>}
//
async function loadConfig() {

    try {
        config = await fetchConfig();

    } catch (err) {
        console.error("Erro ao carregar config, tentando novamente em",
            RETRY_INTERVAL_MS / 1000, "s:", err);

        setTimeout(loadConfig, RETRY_INTERVAL_MS);
        return;
    }

    scheduleConfigRefresh();
    startDashboard();
    scheduleStatePoll();

} /* loadConfig */

// ------------------------------------------------------------------------------------
// busca a configuração de novo e agenda a próxima busca.
// 
// @returns {Promise<void>}
//
async function refreshConfig() {

    try {
        config = await fetchConfig();

    } catch (err) {
        console.warn("Falha ao atualizar config:", err);
    }

    scheduleConfigRefresh();

} /* refreshConfig */

// ------------------------------------------------------------------------------------
// agenda a próxima atualização da configuração para daqui a
// refresh_seconds. Depois de cada tentativa (com sucesso ou não), agenda a
// seguinte: o refresh nunca para. Uma falha mantém a configuração anterior.
//
function scheduleConfigRefresh() {

    if (configTimer) {
        clearTimeout(configTimer);
    }

    const refreshMs = (config.refresh_seconds ?? DEFAULT_REFRESH_SECONDS) * 1000;

    configTimer = setTimeout(refreshConfig, refreshMs);

} /* scheduleConfigRefresh */

// < TILES >---------------------------------------------------------------------------

// ------------------------------------------------------------------------------------
// texto do rodapé do tile.
// 
// @param {object} tile tile da configuração
// @returns {string} data da última atualização, ou aviso de indisponível
//
function buildFooterText(tile) {

    if (tile.file_modified) {
        return `Última atualização em ${tile.file_modified}`;
    }

    return "Data de modificação indisponível";

} /* buildFooterText */

// ------------------------------------------------------------------------------------
// monta a URL de um arquivo de mídia. Os produtos são regravados com o
// mesmo nome, então a URL leva a versão do arquivo (mtime, enviado pelo
// backend em file_version): enquanto o arquivo não muda a URL é a mesma e o
// navegador só revalida (304), sem baixar o GIF de novo. Sem versão
// (arquivo ausente), "?t=<agora>" força uma nova busca.
// 
// @param {string} fileName "<raiz>/<arquivo>" (campo file do tile)
// @param {number} [version] file_version do tile
// @returns {string} URL completa
//
function buildMediaUrl(fileName, version) {

    if (version !== undefined && version !== null) {
        return `${MEDIA_URL}/${fileName}?v=${version}`;
    }

    return `${MEDIA_URL}/${fileName}?t=${Date.now()}`;

} /* buildMediaUrl */

// ------------------------------------------------------------------------------------
// cria o elemento <img> de um tile de imagem ou GIF.
// 
// @param {object} tile tile da configuração ({file, ...})
// @param {HTMLElement} tileElement tile que recebe o erro, se a imagem falhar
// @returns {HTMLImageElement}
//
function createImageElement(tile, tileElement) {

    const img = document.createElement("img");

    img.src = buildMediaUrl(tile.file, tile.file_version);
    img.onerror = () => showTileError(tileElement, tile.file);

    return img;

} /* createImageElement */

// ------------------------------------------------------------------------------------
// cria um tile completo:
//   <div class="tile">
//     <div class="tile-header">título</div>       (só se o tile tiver título)
//     <div class="tile-media"><img|video></div>
//     <div class="tile-footer">data</div>
//   </div>
// 
// @param {object} tile tile da configuração ({type, file, title?, file_modified?})
// @returns {HTMLDivElement}
//
function createTile(tile) {

    const tileElement = document.createElement("div");
    tileElement.className = "tile";

    if (tile.title) {
        const header = document.createElement("div");
        header.className = "tile-header";
        header.textContent = tile.title;
        tileElement.appendChild(header);
    }

    const mediaWrapper = document.createElement("div");
    mediaWrapper.className = "tile-media";

    const media = createTileMedia(tile, tileElement);

    if (media) {
        mediaWrapper.appendChild(media);
    }

    tileElement.appendChild(mediaWrapper);

    const footer = document.createElement("div");
    footer.className = "tile-footer";
    footer.textContent = buildFooterText(tile);
    tileElement.appendChild(footer);

    return tileElement;

} /* createTile */

// ------------------------------------------------------------------------------------
// cria o elemento de mídia de acordo com tile.type.
// 
// @param {object} tile tile da configuração ({type, file, ...})
// @param {HTMLElement} tileElement tile que recebe o erro, se a mídia falhar
// @returns {HTMLElement|null} <img> para "image"/"gif", <video> para
//          "video", ou null para tipo desconhecido
//
function createTileMedia(tile, tileElement) {

    if (tile.type === "image" || tile.type === "gif") {
        return createImageElement(tile, tileElement);
    }

    if (tile.type === "video") {
        return createVideoElement(tile, tileElement);
    }

    return null;

} /* createTileMedia */

// ------------------------------------------------------------------------------------
// cria o elemento <video> de um tile de vídeo: começa sozinho, sem som e
// em loop. (Navegadores só permitem autoplay de vídeo sem som.)
// 
// @param {object} tile tile da configuração ({file, ...})
// @param {HTMLElement} tileElement tile que recebe o erro, se o vídeo falhar
// @returns {HTMLVideoElement}
//
function createVideoElement(tile, tileElement) {

    const video = document.createElement("video");

    video.src = buildMediaUrl(tile.file, tile.file_version);
    video.autoplay = true;
    video.loop = true;
    video.muted = true;
    video.playsInline = true;
    video.onerror = () => showTileError(tileElement, tile.file);

    return video;

} /* createVideoElement */

// ------------------------------------------------------------------------------------
// mídia que não carregou: troca-a pela imagem de "indisponível", mantendo o
// título, e avisa no rodapé. Se a própria imagem de indisponível falhar (ou
// o tile não tiver .tile-media), o tile inteiro vira uma mensagem de erro.
// 
// @param {HTMLElement} tileElement o <div class="tile">
// @param {string} fileName arquivo que não carregou
//
function showTileError(tileElement, fileName) {

    const message = `Arquivo não encontrado: ${fileName}`;
    const mediaWrapper = tileElement.querySelector(".tile-media");

    // "tile--unavailable" já marcado = foi a imagem de indisponível que falhou
    if (!mediaWrapper || tileElement.classList.contains("tile--unavailable")) {
        tileElement.classList.add("tile--error");
        tileElement.textContent = message;
        return;
    }

    tileElement.classList.add("tile--unavailable");

    const img = document.createElement("img");
    img.src = UNAVAILABLE_URL;
    img.onerror = () => showTileError(tileElement, fileName);

    mediaWrapper.replaceChildren(img);

    const footer = tileElement.querySelector(".tile-footer");

    if (footer) {
        footer.textContent = message;
    }

} /* showTileError */

// < GRADE >---------------------------------------------------------------------------

// ------------------------------------------------------------------------------------
// ajusta a grade CSS do #dashboard ao número de tiles:
//   1 tile  -> 1 coluna x 1 linha
//   2 tiles -> 2 colunas x 1 linha
//   3 tiles -> 2 colunas x 2 linhas (uma célula fica vazia)
// com layout "rows": 1 coluna e uma linha por tile, sem limite.
// 
// @param {number} tileCount número de tiles da página (limitado a MAX_TILES,
//        exceto em "rows")
// @param {string} [layout] layout da página ("rows" ou ausente)
//
function applyGrid(tileCount, layout) {

    const dashboard = document.getElementById("dashboard");

    if (layout === "rows") {
        dashboard.style.gridTemplateColumns = "1fr";
        dashboard.style.gridTemplateRows = `repeat(${Math.max(tileCount, 1)}, 1fr)`;
        return;
    }

    const count = Math.min(tileCount, MAX_TILES);

    if (count === 1) {
        dashboard.style.gridTemplateColumns = "1fr";
        dashboard.style.gridTemplateRows = "1fr";
        return;
    }

    if (count === 2) {
        dashboard.style.gridTemplateColumns = "1fr 1fr";
        dashboard.style.gridTemplateRows = "1fr";
        return;
    }

    dashboard.style.gridTemplateColumns = "1fr 1fr";
    dashboard.style.gridTemplateRows = "1fr 1fr";

} /* applyGrid */

// < TÍTULO E BARRA DE PROGRESSO >-----------------------------------------------------

// ------------------------------------------------------------------------------------
// anima a barra de progresso de 0% a 100% ao longo da duração da página.
// 
// @param {number} durationSeconds duração da página
//
function animateProgressBar(durationSeconds) {

    const fill = document.getElementById("progress-fill");

    // volta para 0% sem animação
    fill.style.transition = "none";
    fill.style.width = "0%";

    // ler o tamanho obriga o navegador a aplicar o 0% agora; sem isso ele
    // juntaria as duas mudanças e a barra não voltaria ao início
    fill.getBoundingClientRect();

    fill.style.transition = `width ${durationSeconds}s linear`;
    fill.style.width = "100%";

} /* animateProgressBar */

// ------------------------------------------------------------------------------------
// troca o título da página com fade: esconde, espera o fade-out e mostra
// o novo texto. Durante o alerta o título é ALERT_TITLE. O aviso da página
// (page.notice, ex.: radares de nowcast ocultos) vai em #page-notice.
// 
// @param {object} page página da configuração ({name, notice?, ...})
//
function updateTitle(page) {

    const title = document.getElementById("page-title");
    const notice = document.getElementById("page-notice");

    title.classList.remove("visible");

    // um título pendente de uma troca anterior (< FADE_DURATION_MS atrás)
    // escreveria o nome errado por cima deste
    clearTimeout(titleTimer);

    titleTimer = setTimeout(() => {
        title.textContent = inAlert ? ALERT_TITLE : page.name;
        title.classList.add("visible");

        if (notice) {
            notice.textContent = inAlert ? "" : (page.notice ?? "");
        }
    }, FADE_DURATION_MS);

} /* updateTitle */

// < PÁGINAS >-------------------------------------------------------------------------

// ------------------------------------------------------------------------------------
// coloca os tiles da página no #dashboard (substitui os anteriores),
// mostra o dashboard e inicia a barra de progresso.
// 
// @param {object} page página da configuração ({duration, tiles, layout?, ...})
//
function renderPage(page) {

    const dashboard = document.getElementById("dashboard");

    // em "rows" o backend já definiu os tiles (nowcast: oflow e u-net)
    const tiles = page.layout === "rows" ? page.tiles : page.tiles.slice(0, MAX_TILES);

    dashboard.innerHTML = "";
    applyGrid(tiles.length, page.layout);

    for (const tile of tiles) {
        dashboard.appendChild(createTile(tile));
    }

    dashboard.classList.add("dashboard--visible");

    animateProgressBar(page.duration);

} /* renderPage */

// ------------------------------------------------------------------------------------
// agenda a troca para a página seguinte (dá a volta no fim da lista).
// 
// @param {number} durationSeconds quanto tempo a página atual fica na tela
//
function scheduleNextPage(durationSeconds) {

    pageTimer = setTimeout(() => {
        currentPage = (currentPage + 1) % config.pages.length;
        showPage(currentPage);
    }, durationSeconds * 1000);

} /* scheduleNextPage */

// ------------------------------------------------------------------------------------
// mostra uma página: cancela a troca agendada, faz o fade-out, troca o
// conteúdo (renderPage) e agenda a próxima página.
//
// o índice dá a volta na lista: o número de páginas muda a cada refresh
// (radares de nowcast entram e saem), então um currentPage guardado antes
// pode ter ficado fora da faixa (ex.: ao sair do alerta).
// 
// @param {number} index índice da página em config.pages (qualquer inteiro)
//
function showPage(index) {

    if (pageTimer) {
        clearTimeout(pageTimer);
        pageTimer = null;
    }

    const pageCount = config.pages.length;

    if (pageCount === 0) {
        console.error("Configuração sem páginas: nada a exibir.");
        return;
    }

    currentPage = ((index % pageCount) + pageCount) % pageCount;

    const page = config.pages[currentPage];
    const dashboard = document.getElementById("dashboard");

    updateTitle(page);

    dashboard.classList.remove("dashboard--visible");

    // sem isso, duas trocas em menos de FADE_DURATION_MS (ex.: alerta logo
    // após a rotação) renderizariam a página anterior por cima da nova
    clearTimeout(renderTimer);
    renderTimer = setTimeout(() => renderPage(page), FADE_DURATION_MS);

    // em alerta a página fica presa na tela
    if (!inAlert) {
        scheduleNextPage(page.duration);
    }

} /* showPage */

// ------------------------------------------------------------------------------------
// começa o ciclo de páginas pela primeira.
//
function startDashboard() {

    currentPage = 0;
    showPage(currentPage);

} /* startDashboard */

// < ALERTA PRIORITÁRIO >-------------------------------------------------------------

// ------------------------------------------------------------------------------------
// agenda a próxima consulta ao estado do alerta.
//
function scheduleStatePoll() {

    setTimeout(pollState, STATE_POLL_MS);

} /* scheduleStatePoll */

// ------------------------------------------------------------------------------------
// consulta /api/state e entra/sai do alerta conforme a resposta. Falha de
// rede ou HTTP mantém o estado atual. Sempre agenda a próxima consulta.
// 
// @returns {Promise<void>}
//
async function pollState() {

    try {
        const response = await fetch(STATE_URL);

        if (response.ok) {
            const state = await response.json();
            setAlert(state.alert === true);
        }

    } catch (err) {
        console.warn("Falha ao consultar o estado:", err);
    }

    scheduleStatePoll();

} /* pollState */

// ------------------------------------------------------------------------------------
// liga ou desliga o alerta prioritário (não faz nada se já está no estado
// pedido).
//   ligar:    <body class="alert"> (cabeçalho vermelho, barra amarela) e
//             página ALERT_PAGE_INDEX fixa;
//   desligar: tira a classe e retoma o ciclo a partir da página atual.
// 
// @param {boolean} active true = alerta ativo
//
function setAlert(active) {

    if (active === inAlert) {
        return;
    }

    inAlert = active;
    document.body.classList.toggle("alert", active);

    if (!config) {
        return;
    }

    if (active) {
        currentPage = ALERT_PAGE_INDEX % config.pages.length;
    }

    showPage(currentPage);

} /* setAlert */

// < INICIALIZAÇÃO >-------------------------------------------------------------------

// no navegador (carregado por <script>) "module" não existe: inicia sozinho.
// No Node (testes unitários) "module" existe: só exporta as funções abaixo,
// sem iniciar. Não remova esta checagem.
if (typeof module === "undefined") {
    loadConfig();
}

// EXPORTS (Node/CommonJS — usado apenas pelos testes unitários)

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        fetchConfig,
        loadConfig,
        scheduleConfigRefresh,
        refreshConfig,
        buildMediaUrl,
        showTileError,
        createImageElement,
        createVideoElement,
        createTileMedia,
        buildFooterText,
        createTile,
        applyGrid,
        updateTitle,
        animateProgressBar,
        renderPage,
        scheduleNextPage,
        showPage,
        startDashboard,
        resolveApiBase,
        pollState,
        setAlert,
    };
}

// < the end >-------------------------------------------------------------------------

"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const num = (v, d = 0) => (v === null || v === undefined ? "—" : Number(v).toFixed(d));

let ESTADO = {};
let GONDOLA = null;   // respuesta viva de la auditoría abierta
let SEMILLAS = [];    // índices marcados a mano
let DOC = null;
let FICHA = null;

// ------------------------------------------------------------------ básicos

function aviso(texto, tipo = "") {
  const t = document.createElement("div");
  t.className = "toast " + tipo;
  t.textContent = texto;
  $("#aviso").append(t);
  setTimeout(() => t.remove(), 5200);
}

function cargando(activo, texto = "Procesando…") {
  $("#cargando-texto").textContent = texto;
  $("#cargando").hidden = !activo;
}

async function api(url, opciones = {}) {
  const r = await fetch(url, opciones);
  if (!r.ok) {
    let detalle = r.statusText;
    try { detalle = (await r.json()).detail || detalle; } catch (e) { /* respuesta no JSON */ }
    throw new Error(detalle);
  }
  const tipo = r.headers.get("content-type") || "";
  return tipo.includes("json") ? r.json() : r.text();
}

function kpi(valor, etiqueta, clase = "") {
  return `<div class="kpi ${clase}"><div class="v">${valor}</div><div class="e">${etiqueta}</div></div>`;
}

function tabla(destino, columnas, filas) {
  const cab = columnas.map(c => `<th class="${c.num ? "num" : ""}">${c.titulo}</th>`).join("");
  const cuerpo = filas.map(f =>
    "<tr>" + columnas.map(c => `<td class="${c.num ? "num" : ""}">${c.valor(f)}</td>`).join("") + "</tr>"
  ).join("");
  destino.innerHTML = `<thead><tr>${cab}</tr></thead><tbody>${cuerpo}</tbody>`;
}

// pestañas
$$("#pestanas button").forEach(b => b.addEventListener("click", () => {
  $$("#pestanas button").forEach(x => x.classList.toggle("activa", x === b));
  $$(".vista").forEach(v => v.classList.toggle("activa", v.id === "vista-" + b.dataset.vista));
  if (b.dataset.vista === "bitacora") cargarBitacora();
  if (b.dataset.vista === "tablero") cargarTablero();
}));

// zona de arrastre reutilizable
function zonaSoltar(zona, input, alSoltar) {
  zona.addEventListener("click", () => input.click());
  ["dragenter", "dragover"].forEach(e => zona.addEventListener(e, ev => {
    ev.preventDefault(); zona.classList.add("encima");
  }));
  ["dragleave", "drop"].forEach(e => zona.addEventListener(e, ev => {
    ev.preventDefault(); zona.classList.remove("encima");
  }));
  zona.addEventListener("drop", ev => {
    const f = ev.dataTransfer.files[0];
    if (f) { input.files = ev.dataTransfer.files; alSoltar(f); }
  });
  input.addEventListener("change", () => input.files[0] && alSoltar(input.files[0]));
}

// ------------------------------------------------------------------ arranque

async function arrancar() {
  try {
    ESTADO = await api("/api/estado");
  } catch (e) {
    aviso("No se pudo hablar con el servidor: " + e.message, "error");
    return;
  }
  const p = $("#estado-ia");
  if (ESTADO.ia.activa) {
    p.textContent = "IA activa · " + ESTADO.ia.modelo;
    p.className = "pastilla ok";
  } else {
    p.textContent = "Modo local (sin llave de IA)";
    p.className = "pastilla local";
    p.title = ESTADO.ia.detalle;
  }

  const imagenes = ESTADO.muestras.filter(m => /gondola/i.test(m));
  const docs = ESTADO.muestras.filter(m => !/gondola/i.test(m));
  $("#muestras-gondola").innerHTML = imagenes.map(
    (m, i) => `<button data-m="${m}">Góndola de prueba ${i + 1}</button>`).join("");
  $("#muestras-doc").innerHTML = docs.map(
    m => `<button data-m="${m}">${m.replace(/\.[a-z]+$/i, "").replace(/_/g, " ")}</button>`).join("");
  $$("#muestras-gondola button").forEach(b =>
    b.addEventListener("click", () => analizarGondola({ muestra: b.dataset.m })));
  $$("#muestras-doc button").forEach(b =>
    b.addEventListener("click", () => leerDoc({ muestra: b.dataset.m })));

  $("#tipo-doc").innerHTML = Object.entries(ESTADO.plantillas)
    .map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  $("#radar-fuentes").textContent = "Fuentes: " + ESTADO.fuentes_radar.join(" · ");
}

// ------------------------------------------------------------------ góndola

$("#objetivo").addEventListener("input", e => {
  $("#objetivo-val").textContent = e.target.value + "%";
});
$("#sensibilidad").addEventListener("input", e => {
  $("#sensibilidad-val").textContent = e.target.value;
});

let ARCHIVO_GONDOLA = null;
zonaSoltar($("#soltar-gondola"), $("#archivo-gondola"), f => {
  ARCHIVO_GONDOLA = f;
  $("#soltar-gondola").querySelector("span").innerHTML =
    `<strong>${f.name}</strong><br><small>lista para analizar</small>`;
});

$("#btn-analizar").addEventListener("click", () => analizarGondola({}));

async function analizarGondola({ muestra }) {
  if (!muestra && !ARCHIVO_GONDOLA) { aviso("Primero elige una foto.", "error"); return; }
  const fd = new FormData();
  if (muestra) fd.append("muestra", muestra);
  else fd.append("archivo", ARCHIVO_GONDOLA);
  fd.append("punto_venta", $("#punto-venta").value);
  fd.append("objetivo", $("#objetivo").value);
  fd.append("sensibilidad", $("#sensibilidad").value);
  fd.append("tiling", $("#tiling").checked);
  fd.append("ensamble", $("#ensamble").checked);
  cargando(true, "Detectando productos en la góndola…");
  try {
    GONDOLA = await api("/api/gondola/analizar", { method: "POST", body: fd });
    SEMILLAS = [];
    pintarGondola();
    aviso(`${GONDOLA.indicadores.facings_totales} caras detectadas en ${GONDOLA.meta.segundos} s.`, "ok");
  } catch (e) {
    aviso("Falló el análisis: " + e.message, "error");
  } finally { cargando(false); }
}

function pintarGondola() {
  const d = GONDOLA, i = d.indicadores;
  $("#gondola-vacio").hidden = true;
  $("#gondola-resultado").hidden = false;

  const claseShare = i.objetivo_share === undefined ? "" : (i.cumple_planograma ? "bien" : "mal");
  $("#kpis-gondola").innerHTML =
    kpi(i.facings_totales, "caras detectadas") +
    kpi(i.facings_marca, "caras de la marca") +
    kpi(i.share_of_shelf + "%", "share of shelf" +
      (i.objetivo_share !== undefined ? ` · objetivo ${i.objetivo_share}%` : ""), claseShare) +
    kpi(i.share_por_area + "%", "share por área ocupada") +
    kpi(i.agotados, "espacios vacíos", i.agotados ? "mal" : "bien") +
    kpi(i.ocupacion_lineal + "%", "ocupación del lineal") +
    kpi(d.meta.segundos + " s", "análisis · " + i.baldas.length + " baldas");

  $("#alertas-gondola").innerHTML = i.alertas.map(
    a => `<div class="alerta ${a.nivel}">${a.texto}</div>`).join("");

  const w = d.meta.ancho, h = d.meta.alto;
  const cajas = d.detecciones.map((x, n) => {
    const clase = x.tipo === "vacio" ? "vacio" : (x.marca ? "prod marca" : "prod");
    return `<rect class="${clase}" data-i="${n}" x="${x.x1}" y="${x.y1}"` +
      ` width="${Math.max(1, x.x2 - x.x1)}" height="${Math.max(1, x.y2 - x.y1)}" rx="2"></rect>`;
  }).join("");
  $("#lienzo").innerHTML =
    `<img src="${d.imagen_original}" alt="góndola">` +
    `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${cajas}</svg>`;
  $$("#lienzo rect.prod").forEach(r => r.addEventListener("click", () => alternarMarca(+r.dataset.i)));

  tabla($("#tabla-baldas"),
    [{ titulo: "Balda", valor: f => f.balda, num: true },
     { titulo: "Productos", valor: f => f.productos, num: true },
     { titulo: "De la marca", valor: f => f.marca, num: true },
     { titulo: "Share", valor: f => f.productos ? (f.marca / f.productos * 100).toFixed(0) + "%" : "—", num: true },
     { titulo: "Vacíos", valor: f => f.vacios || "", num: true }],
    i.baldas);
}

async function alternarMarca(indice) {
  const pos = SEMILLAS.indexOf(indice);
  if (pos >= 0) SEMILLAS.splice(pos, 1); else SEMILLAS.push(indice);
  await recalcularMarca();
}

async function recalcularMarca() {
  cargando(true, "Buscando las caras iguales…");
  try {
    GONDOLA = await api("/api/gondola/marca", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sesion: GONDOLA.sesion, indices: SEMILLAS,
                             propagar: $("#propagar").checked,
                             umbral: +$("#umbral").value }),
    });
    pintarGondola();
  } catch (e) { aviso(e.message, "error"); } finally { cargando(false); }
}

$("#btn-limpiar-marca").addEventListener("click", () => { SEMILLAS = []; recalcularMarca(); });

$("#umbral").addEventListener("input", e => { $("#umbral-val").textContent = e.target.value; });
$("#umbral").addEventListener("change", () => { if (SEMILLAS.length) recalcularMarca(); });

$("#objetivo").addEventListener("change", async () => {
  if (!GONDOLA) return;
  GONDOLA = await api("/api/gondola/objetivo", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sesion: GONDOLA.sesion, objetivo: $("#objetivo").value }) });
  pintarGondola();
});

$("#btn-guardar-gondola").addEventListener("click", async () => {
  if (!GONDOLA) return;
  try {
    const r = await api("/api/gondola/guardar", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sesion: GONDOLA.sesion, punto_venta: $("#punto-venta").value,
                             notas: $("#notas-gondola").value }) });
    aviso(`Auditoría guardada como corrida #${r.id}.`, "ok");
  } catch (e) { aviso(e.message, "error"); }
});

// --------------------------------------------------------------- documentos

let ARCHIVO_DOC = null;
zonaSoltar($("#soltar-doc"), $("#archivo-doc"), f => {
  ARCHIVO_DOC = f;
  $("#soltar-doc").querySelector("span").innerHTML =
    `<strong>${f.name}</strong><br><small>listo para leer</small>`;
});
$("#btn-leer-doc").addEventListener("click", () => leerDoc({}));

async function leerDoc({ muestra }) {
  if (!muestra && !ARCHIVO_DOC) { aviso("Primero elige un documento.", "error"); return; }
  const fd = new FormData();
  if (muestra) fd.append("muestra", muestra); else fd.append("archivo", ARCHIVO_DOC);
  fd.append("tipo", $("#tipo-doc").value);
  fd.append("usar_ia", $("#doc-ia").checked);
  cargando(true, "Leyendo el documento…");
  try {
    DOC = await api("/api/documento/procesar", { method: "POST", body: fd });
    pintarDoc();
    if (DOC.error_ia) aviso("El modelo falló, se usaron las reglas: " + DOC.error_ia, "error");
  } catch (e) { aviso("Falló la lectura: " + e.message, "error"); }
  finally { cargando(false); }
}

function pintarDoc() {
  $("#doc-vacio").hidden = true;
  $("#doc-resultado").hidden = false;
  const errores = DOC.avisos.filter(a => a.nivel === "error").length;
  $("#kpis-doc").innerHTML =
    kpi(DOC.completitud + "%", "campos diligenciados", DOC.completitud > 80 ? "bien" : "ojo") +
    kpi(Object.keys(DOC.campos).length, "campos de la plantilla") +
    kpi(errores, "inconsistencias", errores ? "mal" : "bien") +
    kpi(DOC.segundos + " s", "lectura · motor: " + DOC.motor);

  $("#avisos-doc").innerHTML = DOC.avisos.map(a =>
    `<div class="alerta ${a.nivel === "error" ? "alta" : "media"}"><b>${a.campo}</b> · ${a.texto}</div>`
  ).join("");

  const porCampo = Object.fromEntries(DOC.avisos.map(a => [a.campo, a.nivel]));
  $("#campos-doc").innerHTML = Object.entries(DOC.campos).map(([k, v]) =>
    `<div class="campo ${porCampo[k] === "error" ? "error" : porCampo[k] ? "aviso" : ""}">
       <label for="c-${k}">${k.replace(/_/g, " ")}</label>
       <input id="c-${k}" data-campo="${k}" value="${(v || "").replace(/"/g, "&quot;")}">
     </div>`).join("");
  $("#img-doc").src = DOC.imagen;
  $("#ocr-doc").textContent = DOC.texto_ocr;
}

$("#btn-guardar-doc").addEventListener("click", async () => {
  if (!DOC) return;
  const campos = {};
  $$("#campos-doc input").forEach(i => campos[i.dataset.campo] = i.value);
  try {
    const r = await api("/api/documento/guardar", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...DOC, campos }) });
    aviso(`Documento guardado como corrida #${r.id}.`, "ok");
  } catch (e) { aviso(e.message, "error"); }
});

$("#btn-csv").addEventListener("click", () => { window.location = "/api/documento/csv"; });

// -------------------------------------------------------------------- radar

$("#btn-radar").addEventListener("click", async () => {
  cargando(true, "Barriendo fuentes y clasificando…");
  try {
    const r = await api(`/api/radar?dias=${$("#radar-dias").value}` +
      `&limite=${$("#radar-limite").value}&usar_ia=${$("#radar-ia").checked}`);
    $("#radar-resumen").hidden = false;
    $("#radar-resumen").innerHTML =
      `<div class="kpis">` +
      kpi(r.items.length, "publicaciones") +
      kpi(r.accionables, "con relevancia 4 o 5", r.accionables ? "bien" : "") +
      kpi(r.segundos + " s", "barrido · motor: " + r.motor) +
      kpi(r.fuentes_totales - r.fuentes_fallidas.length + "/" + r.fuentes_totales, "fuentes respondieron",
          r.fuentes_fallidas.length ? "ojo" : "bien") +
      `</div>` +
      (r.fuentes_fallidas.length ? `<p class="nota">No respondieron: ${r.fuentes_fallidas.join(", ")}</p>` : "") +
      (r.error_ia ? `<div class="alerta media">El modelo falló y se clasificó por reglas: ${r.error_ia}</div>` : "");

    $("#radar-lista").innerHTML = r.items.map(i => `
      <div class="tarjeta">
        <div class="meta">
          <span class="rel r${i.relevancia}">${i.relevancia}</span>
          <span><b>${i.frente}</b></span><span>${i.fuente}</span><span>${i.fecha || ""}</span>
        </div>
        <h4><a href="${i.url}" target="_blank" rel="noopener">${i.titulo}</a></h4>
        <p>${i.por_que}</p>
        ${i.uso ? `<p class="uso"><b>Uso posible:</b> ${i.uso}</p>` : ""}
      </div>`).join("");
    aviso(`Barrido listo: ${r.accionables} publicaciones accionables.`, "ok");
  } catch (e) { aviso("Falló el barrido: " + e.message, "error"); }
  finally { cargando(false); }
});

// ----------------------------------------------------------------- bitácora

async function cargarBitacora() {
  try {
    const b = await api("/api/bitacora");
    tabla($("#tabla-bitacora"),
      [{ titulo: "", valor: c => `<input type="checkbox" class="sel" value="${c.id}">` },
       { titulo: "#", valor: c => c.id, num: true },
       { titulo: "Fecha", valor: c => c.fecha.slice(0, 16).replace("T", " ") },
       { titulo: "Módulo", valor: c => c.modulo },
       { titulo: "Título", valor: c => c.titulo },
       { titulo: "Modelo", valor: c => c.modelo || "—" },
       { titulo: "Métricas", valor: c => resumenMetricas(c.metricas) },
       { titulo: "Seg.", valor: c => num(c.segundos, 1), num: true },
       { titulo: "Min. manual", valor: c => num(c.minutos_manual, 1), num: true }],
      b.corridas);
    const p = await api("/api/pocs");
    $("#lista-pocs").innerHTML = p.pocs.length ? p.pocs.map(x => `
      <div class="tarjeta">
        <div class="meta"><span>#${x.id}</span><span>${x.fecha.slice(0, 10)}</span>
          <span><b>${x.estado}</b></span><span>corridas: ${(x.corridas || []).join(", ") || "—"}</span></div>
        <h4>${x.titulo}</h4>
        <p><b>Hipótesis:</b> ${x.hipotesis}</p>
        <p><b>Conclusión:</b> ${x.conclusion}</p>
        <button class="secundario" data-borrar="${x.id}">Borrar</button>
      </div>`).join("") : `<p class="nota">Todavía no hay POCs documentados.</p>`;
    $$("#lista-pocs button[data-borrar]").forEach(b2 => b2.addEventListener("click", async () => {
      await api("/api/poc/" + b2.dataset.borrar, { method: "DELETE" });
      cargarBitacora();
    }));
  } catch (e) { aviso(e.message, "error"); }
}

function resumenMetricas(m) {
  if (!m) return "—";
  const claves = ["share_of_shelf", "facings_totales", "agotados", "completitud",
                  "publicaciones", "accionables"];
  const partes = claves.filter(k => m[k] !== undefined).map(k => `${k}: ${m[k]}`);
  return partes.join(" · ") || "—";
}

$("#btn-ficha").addEventListener("click", async () => {
  const ids = $$("#tabla-bitacora .sel:checked").map(i => +i.value);
  if (!ids.length) { aviso("Selecciona al menos una corrida de la tabla.", "error"); return; }
  cargando(true, "Redactando la ficha del POC…");
  try {
    FICHA = await api("/api/poc/generar", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }) });
    $("#panel-ficha").hidden = false;
    $("#ficha-meta").textContent =
      `Generada por ${FICHA.motor} a partir de las corridas ${ids.join(", ")}.` +
      (FICHA.error_ia ? ` El modelo falló (${FICHA.error_ia}), se usó la plantilla.` : "");
    $("#f-titulo").value = FICHA.titulo || "";
    $("#f-hipotesis").value = FICHA.hipotesis || "";
    $("#f-metodo").value = FICHA.metodo || "";
    $("#f-resultado").value = FICHA.resultado || "";
    $("#f-conclusion").value = FICHA.conclusion || "";
    $("#f-estado").value = FICHA.estado || "requiere ajustes";
    $("#panel-ficha").scrollIntoView({ behavior: "smooth" });
  } catch (e) { aviso(e.message, "error"); } finally { cargando(false); }
});

function fichaEditada() {
  return { ...FICHA, titulo: $("#f-titulo").value, hipotesis: $("#f-hipotesis").value,
           metodo: $("#f-metodo").value, resultado: $("#f-resultado").value,
           conclusion: $("#f-conclusion").value, estado: $("#f-estado").value };
}

$("#btn-guardar-poc").addEventListener("click", async () => {
  try {
    const r = await api("/api/poc/guardar", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fichaEditada()) });
    aviso(`POC #${r.id} documentado.`, "ok");
    cargarBitacora();
  } catch (e) { aviso(e.message, "error"); }
});

$("#btn-md").addEventListener("click", async () => {
  const md = await api("/api/poc/markdown", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fichaEditada()) });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
  a.download = ($("#f-titulo").value || "poc").replace(/\W+/g, "_").toLowerCase() + ".md";
  a.click();
});

// ------------------------------------------------------------------ tablero

async function cargarTablero() {
  try {
    const t = await api("/api/tablero");
    const r = t.resumen;
    $("#kpis-tablero").innerHTML =
      kpi(r.corridas, "corridas registradas") +
      kpi(t.total_auditorias, "auditorías de góndola") +
      kpi(r.pocs, "POCs documentados") +
      kpi(r.minutos_ahorrados + " min", "ahorro estimado vs. manual", "bien") +
      kpi(r.minutos_maquina + " min", "tiempo de máquina");

    barras($("#grafico-agotados"), t.puntos.map(p => ({
      etiqueta: p.punto_venta, valor: p.agotados })));
    linea($("#grafico-share"), t.serie.filter(s => s.share !== undefined && s.share !== null));

    tabla($("#tabla-puntos"),
      [{ titulo: "Punto de venta", valor: p => p.punto_venta },
       { titulo: "Auditorías", valor: p => p.auditorias, num: true },
       { titulo: "Caras revisadas", valor: p => p.facings, num: true },
       { titulo: "Share promedio", valor: p => p.share_promedio === null ? "—" : p.share_promedio + "%", num: true },
       { titulo: "Agotados", valor: p => p.agotados, num: true }],
      t.puntos);
  } catch (e) { aviso(e.message, "error"); }
}

function barras(destino, datos) {
  if (!datos.length) { destino.innerHTML = `<p class="nota">Sin datos todavía.</p>`; return; }
  const W = 600, H = 200, mi = 30, mb = 34;
  const max = Math.max(1, ...datos.map(d => d.valor));
  // Con pocos puntos de venta una barra sola ocuparía todo el ancho y se ve
  // como un bloque de color; se limita el grosor y se centra el grupo.
  const paso = Math.min((W - mi) / datos.length, 110);
  const ancho = paso;
  const inicio = mi + ((W - mi) - paso * datos.length) / 2;
  const barras = datos.map((d, i) => {
    const alto = (H - mb) * (d.valor / max);
    const x = inicio + i * paso + paso * 0.15;
    return `<rect class="barra" x="${x}" y="${H - mb - alto}" width="${ancho * 0.7}"
              height="${alto}" rx="3"></rect>
            <text x="${x + ancho * 0.35}" y="${H - mb - alto - 4}" text-anchor="middle">${d.valor}</text>
            <text x="${x + ancho * 0.35}" y="${H - mb + 14}" text-anchor="middle">${
              d.etiqueta.length > 14 ? d.etiqueta.slice(0, 13) + "…" : d.etiqueta}</text>`;
  }).join("");
  destino.innerHTML = `<svg class="gr" viewBox="0 0 ${W} ${H}">
    <line class="eje" x1="${mi}" y1="${H - mb}" x2="${W}" y2="${H - mb}"></line>${barras}</svg>`;
}

function linea(destino, datos) {
  if (datos.length < 1) { destino.innerHTML = `<p class="nota">Sin datos todavía.</p>`; return; }
  const W = 600, H = 200, mi = 34, mb = 30;
  const max = Math.max(100, ...datos.map(d => d.share));
  const px = i => mi + (datos.length === 1 ? (W - mi) / 2 : i * (W - mi - 10) / (datos.length - 1));
  const py = v => H - mb - (H - mb - 12) * (v / max);
  const puntos = datos.map((d, i) => `${px(i)},${py(d.share)}`).join(" ");
  destino.innerHTML = `<svg class="gr" viewBox="0 0 ${W} ${H}">
    <line class="eje" x1="${mi}" y1="${H - mb}" x2="${W}" y2="${H - mb}"></line>
    <line class="eje" x1="${mi}" y1="12" x2="${mi}" y2="${H - mb}"></line>
    <text x="4" y="16">${max}%</text><text x="4" y="${H - mb}">0%</text>
    <polyline class="linea" points="${puntos}"></polyline>
    ${datos.map((d, i) => `<circle class="punto" cx="${px(i)}" cy="${py(d.share)}" r="3.5">
        <title>#${d.id} · ${d.punto_venta} · ${d.share}%</title></circle>
      <text x="${px(i)}" y="${H - mb + 14}" text-anchor="middle">#${d.id}</text>`).join("")}
  </svg>`;
}

arrancar();

import { useEffect, useRef, useState } from "react";
import { requestJson } from "./api/stream";
import { ZodiacScene, type Layer } from "./scene/ZodiacScene";
import { formatInstant, sceneSchema, type Manifest, type SceneData } from "./scene/schema";

export function ScenePanel({ manifest, conversation }: { manifest: Manifest; conversation: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const viewer = useRef<ZodiacScene>();
  const [data, setData] = useState<SceneData>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [focus, setFocus] = useState("");
  const [layers, setLayers] = useState<Record<Layer, boolean>>({
    signs: true, stars: true, boundaries: true,
  });
  const base = `/api/renders/${manifest.id}`;
  const query = `?conversation_id=${encodeURIComponent(conversation)}`;

  useEffect(() => {
    const controller = new AbortController();
    setData(undefined);
    setError("");
    setFocus("");
    let active: ZodiacScene | undefined;
    requestJson(`${base}/data${query}`, { signal: controller.signal }).then(value => {
      if (controller.signal.aborted || !canvas.current) return;
      const scene = sceneSchema.parse(value);
      if (scene.instant !== manifest.instant) throw new Error("Le rendu ne correspond pas à la date demandée.");
      active = new ZodiacScene(canvas.current, scene, setError);
      viewer.current = active;
      for (const layer of ["signs", "stars", "boundaries"] as const) {
        active.setLayer(layer, layers[layer]);
      }
      setData(scene);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "Le rendu 3D n'a pas pu être chargé.");
      }
    });
    return () => {
      controller.abort();
      active?.dispose();
      viewer.current = undefined;
    };
  }, [manifest.id, conversation, revision]);

  function layerChange(layer: Layer, checked: boolean) {
    setLayers(previous => ({ ...previous, [layer]: checked }));
    viewer.current?.setLayer(layer, checked);
  }

  return <section className="scene-panel" aria-label="Rendu astronomique interactif">
    <div className="scene-heading">
      <span className="eyebrow">NASA / JPL HORIZONS · BABYLON.JS</span>
      <h1>Le ciel, à votre date.</h1>
      <p>{formatInstant(manifest.instant)}</p>
    </div>
    <div className="canvas-wrap">
      <canvas ref={canvas} tabIndex={0}
        aria-label="Sphère céleste : glisser ou utiliser les flèches pour tourner, molette et touches plus ou moins pour zoomer" />
      {!data && !error && <div className="scene-notice" role="status">Préparation de la sphère céleste…</div>}
      {error && <div className="scene-notice error" role="alert">
        <p>{error}</p><button onClick={() => setRevision(value => value + 1)}>Recharger la 3D</button>
      </div>}
    </div>
    <div className="solar-card">
      <span className="sun-dot" />
      <div><small>SIGNE TROPICAL</small><strong>{manifest.sign}</strong>
        <span>{manifest.degrees.toFixed(4)}° dans le signe</span></div>
      <div><small>CONSTELLATION UAI</small><strong>{manifest.solarConstellation}</strong>
        <span>λ {manifest.longitude.toFixed(7)}° · β {manifest.latitude.toFixed(7)}°</span></div>
    </div>
    <div className="scene-controls">
      <div className="layer-controls">
        {([["stars", "Constellations"], ["signs", "Signes"], ["boundaries", "Frontières UAI"]] as const)
          .map(([layer, label]) => <label key={layer}>
            <input type="checkbox" checked={layers[layer]} disabled={!data}
              onChange={event => layerChange(layer, event.target.checked)} />{label}
          </label>)}
      </div>
      <div className="camera-controls">
        <select aria-label="Orienter vers une constellation" value={focus} disabled={!data}
          onChange={event => { setFocus(event.target.value); viewer.current?.focus(event.target.value); }}>
          <option value="">Vue d'ensemble</option>
          {data?.constellations.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <button disabled={!data} onClick={() => { viewer.current?.reset(); setFocus(""); }}>
          Recentrer
        </button>
      </div>
    </div>
    <footer className="scene-footer">
      <p>{manifest.timeAssumption} Vue géocentrique, tailles et distances non à l'échelle.
        La caméra est interactive ; l'instant astronomique reste celui demandé.</p>
      <div className="links">
        <a href={`${base}/html${query}`}>Télécharger le HTML interactif</a>
        <a href={`${base}/source${query}`}>Éphémérides NASA</a>
        {data && <a href={data.requestUrl} target="_blank" rel="noopener noreferrer">Requête source ↗</a>}
      </div>
      {data && <details><summary>Repères, données et licence</summary>
        <p>12 signes tropicaux de 30°, distincts des 13 constellations, dont Ophiuchus.
          Positions stellaires converties par Astropy avec précession, nutation et aberration ;
          mouvement propre et parallaxe non modélisés.</p>
        <a href={data.catalogueSource} target="_blank" rel="noopener noreferrer">Catalogue D3-Celestial</a>
        <pre>{data.catalogueLicense}</pre>
        <a href="/viewer-licenses.txt" target="_blank" rel="noopener noreferrer">Licences du viewer</a>
      </details>}
    </footer>
  </section>;
}

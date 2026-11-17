import { ArcRotateCamera } from "@babylonjs/core/Cameras/arcRotateCamera";
import { Engine } from "@babylonjs/core/Engines/engine";
import { HemisphericLight } from "@babylonjs/core/Lights/hemisphericLight";
import { Color3, Color4 } from "@babylonjs/core/Maths/math.color";
import { Vector3 } from "@babylonjs/core/Maths/math.vector";
import { StandardMaterial } from "@babylonjs/core/Materials/standardMaterial";
import { DynamicTexture } from "@babylonjs/core/Materials/Textures/dynamicTexture";
import type { AbstractMesh } from "@babylonjs/core/Meshes/abstractMesh";
import { CreateLines, CreateLineSystem } from "@babylonjs/core/Meshes/Builders/linesBuilder";
import { CreatePlane } from "@babylonjs/core/Meshes/Builders/planeBuilder";
import { CreateRibbon } from "@babylonjs/core/Meshes/Builders/ribbonBuilder";
import { CreateSphere } from "@babylonjs/core/Meshes/Builders/sphereBuilder";
import { CreateTube } from "@babylonjs/core/Meshes/Builders/tubeBuilder";
import { Mesh } from "@babylonjs/core/Meshes/mesh";
import { Scene } from "@babylonjs/core/scene";
import type { SceneData } from "./schema";

export type Layer = "signs" | "stars" | "boundaries";

export class ZodiacScene {
  private engine: Engine;
  private scene: Scene;
  private camera: ArcRotateCamera;
  private resize: ResizeObserver;
  private intersection: IntersectionObserver;
  private groups: Record<Layer, AbstractMesh[]> = { signs: [], stars: [], boundaries: [] };
  private fading: { mesh: AbstractMesh; direction: Vector3; label: boolean }[] = [];
  private visible = true;
  private disposed = false;
  private interacted = false;

  constructor(
    private canvas: HTMLCanvasElement,
    private data: SceneData,
    onError: (message: string) => void,
  ) {
    if (!Engine.isSupported()) throw new Error("WebGL est indisponible dans ce navigateur.");
    this.engine = new Engine(canvas, true);
    this.scene = new Scene(this.engine);
    this.scene.useRightHandedSystem = true;
    this.scene.clearColor = Color4.FromHexString("#09162bff");
    this.camera = new ArcRotateCamera(
      "camera", -data.azimuth * Math.PI / 180,
      Math.min(Math.PI - 0.05, Math.max(0.05, (90 - data.elevation) * Math.PI / 180)),
      4.5, Vector3.Zero(), this.scene,
    );
    this.camera.lowerRadiusLimit = 1.7;
    this.camera.upperRadiusLimit = 10;
    this.camera.wheelPrecision = 45;
    this.camera.pinchPrecision = 80;
    this.camera.attachControl(canvas, true);
    new HemisphericLight("ambient", new Vector3(0, 1, 0), this.scene).intensity = 0.9;
    try {
      this.build();
      this.reset();
    } catch (error) {
      this.scene.dispose();
      this.engine.dispose();
      throw error;
    }
    this.scene.onBeforeRenderObservable.add(() => {
      const direction = this.camera.position.normalizeToNew();
      this.fading.forEach(item => {
        item.mesh.visibility = Vector3.Dot(direction, item.direction) > 0
          ? 1 : item.label ? 0 : 0.16;
      });
    });
    this.engine.onContextLostObservable.add(() => onError(
      "Le contexte WebGL a ete perdu. Rechargez ce rendu pour restaurer la vue.",
    ));
    this.resize = new ResizeObserver(() => {
      this.engine.resize();
      if (!this.interacted) this.fit();
    });
    this.resize.observe(canvas);
    this.intersection = new IntersectionObserver(entries => {
      this.visible = entries.some(entry => entry.isIntersecting);
      this.renderState();
    });
    this.intersection.observe(canvas);
    document.addEventListener("visibilitychange", this.renderState);
    canvas.addEventListener("keydown", this.keyboard);
    canvas.addEventListener("pointerdown", this.touch);
    canvas.addEventListener("wheel", this.touch);
    this.renderState();
  }

  private vector(longitude: number, latitude: number, radius = 1): Vector3 {
    const lon = longitude * Math.PI / 180, lat = latitude * Math.PI / 180;
    return new Vector3(
      radius * Math.cos(lat) * Math.cos(lon), radius * Math.sin(lat),
      -radius * Math.cos(lat) * Math.sin(lon),
    );
  }

  private material(name: string, color: string, alpha = 1): StandardMaterial {
    const material = new StandardMaterial(name, this.scene);
    material.diffuseColor = Color3.FromHexString(color);
    material.emissiveColor = material.diffuseColor.scale(0.35);
    material.alpha = alpha;
    material.backFaceCulling = false;
    return material;
  }

  private line(name: string, points: Vector3[], color: string) {
    const mesh = CreateLines(name, { points }, this.scene);
    mesh.color = Color3.FromHexString(color);
    mesh.isPickable = false;
    return mesh;
  }

  private label(name: string, text: string, position: Vector3, color: string, width = 0.48) {
    const texture = new DynamicTexture(`${name}-text`, { width: 512, height: 128 }, this.scene);
    texture.hasAlpha = true;
    // Right-handed billboards expose the reverse face of Babylon's default plane.
    texture.uScale = -1;
    texture.uOffset = 1;
    texture.drawText(text, null, 86, "bold 46px sans-serif", color, "transparent", true);
    const mesh = CreatePlane(name, { width, height: width / 4 }, this.scene);
    mesh.position = position;
    mesh.billboardMode = Mesh.BILLBOARDMODE_ALL;
    mesh.isPickable = false;
    const material = this.material(`${name}-material`, "#ffffff");
    material.diffuseTexture = material.opacityTexture = texture;
    material.disableLighting = true;
    material.emissiveColor = Color3.White();
    mesh.material = material;
    return mesh;
  }

  private build() {
    const { data } = this;
    data.signs.forEach(([name], index) => {
      const start = index * 30, color = data.colors[index];
      const paths = Array.from({ length: 13 }, (_, lon) =>
        Array.from({ length: 37 }, (_, lat) => this.vector(start + lon * 2.5, -90 + lat * 5)));
      const sector = CreateRibbon(`sector-${index}`, {
        pathArray: paths, sideOrientation: Mesh.DOUBLESIDE,
      }, this.scene);
      sector.material = this.material(`sector-material-${index}`, color, 0.065);
      sector.isPickable = false;
      const ring = CreateTube(`ecliptic-${index}`, {
        path: Array.from({ length: 41 }, (_, step) => this.vector(start + step * 0.75, 0)),
        radius: 0.007, tessellation: 8,
      }, this.scene);
      ring.material = this.material(`arc-material-${index}`, color);
      this.groups.signs.push(sector, ring, this.line(`meridian-${index}`, paths[0], color),
        this.label(`sign-${index}`, `${name} · signe`, this.vector(start + 15, -22, 1.08), color, 0.5));
    });
    const solarIndex = data.constellations.findIndex(item => item.name === data.solarConstellation);
    if (solarIndex >= 0) {
      [-1, 0, 1].forEach((offset, index) => {
        const figure = data.constellations[(solarIndex + offset + 13) % 13];
        figure.boundaries.forEach((ring, ringIndex) => {
          const mesh = this.line(`iau-${figure.id}-${ringIndex}`,
            ring.map(([lon, lat]) => this.vector(lon, lat, 1.018)),
            ["#ffad95", "#72f5d0", "#cbb5ff"][index]);
          this.groups.boundaries.push(mesh);
          this.fading.push({
            mesh, direction: this.vector(figure.longitude, figure.latitude), label: false,
          });
        });
      });
    }
    const starMaterial = this.material("stars", "#e9f9ff");
    starMaterial.disableLighting = true;
    starMaterial.emissiveColor = Color3.FromHexString("#e9f9ff");
    const seen = new Set<number>();
    data.constellations.forEach(figure => {
      const positions = new Map(figure.stars.map(star =>
        [star.hip, this.vector(star.longitude, star.latitude, 1.012)]));
      figure.stars.forEach(star => {
        if (seen.has(star.hip)) return;
        const mesh = CreateSphere(`star-${star.hip}`, {
          diameter: Math.max(0.008, 0.025 * Math.pow(10, -0.09 * star.magnitude)), segments: 8,
        }, this.scene);
        mesh.position = positions.get(star.hip)!;
        mesh.material = starMaterial;
        mesh.isPickable = false;
        seen.add(star.hip);
        this.groups.stars.push(mesh);
        this.fading.push({ mesh, direction: mesh.position.normalizeToNew(), label: false });
      });
      const paths = figure.paths.map(path => {
        const points: Vector3[] = [];
        for (let index = 0; index < path.length - 1; index++) {
          const start = positions.get(path[index]), end = positions.get(path[index + 1]);
          if (!start || !end) throw new Error("Tracé de constellation incomplet.");
          for (let step = 0; step < 16; step++) {
            points.push(Vector3.Lerp(start, end, step / 16).normalize().scale(1.012));
          }
        }
        const last = positions.get(path[path.length - 1]);
        if (!last) throw new Error("Tracé de constellation vide.");
        points.push(last);
        return points;
      });
      const mesh = CreateLineSystem(`constellation-${figure.id}`, {
        lines: paths,
      }, this.scene);
      mesh.color = Color3.FromHexString("#9be7ff");
      mesh.isPickable = false;
      const direction = this.vector(figure.longitude, figure.latitude);
      const labelLat = Math.max(-85, Math.min(85, figure.latitude + (figure.latitude >= 0 ? 5 : -5)));
      const caption = this.label(`label-${figure.id}`, figure.name,
        this.vector(figure.longitude, labelLat, 1.045), "#b2efff", 0.42);
      this.groups.stars.push(mesh, caption);
      this.fading.push({ mesh, direction, label: false }, { mesh: caption, direction, label: true });
    });
    [-60, -30, 30, 60].forEach(latitude => {
      this.line(`parallel-${latitude}`,
        Array.from({ length: 181 }, (_, step) => this.vector(step * 2, latitude)), "#adbdce").alpha = 0.2;
    });
    const earth = CreateSphere("earth", { diameter: 0.26, segments: 32 }, this.scene);
    earth.material = this.material("earth-material", "#238bc2");
    this.label("earth-label", "TERRE", new Vector3(0, 0.23, 0), "#edf3fc", 0.3);
    this.line("equinox", [Vector3.Zero(), this.vector(0, 0, 1.25)], "#edf3fc");
    this.label("equinox-label", "0° · Équinoxe de mars", this.vector(0, -8, 1.27), "#edf3fc", 0.65);
    this.label("north", "Pôle nord écliptique", new Vector3(0, 1.15, 0), "#edf3fc", 0.65);
    const position = this.vector(data.longitude, data.latitude);
    const sun = CreateSphere("sun", { diameter: 0.075, segments: 24 }, this.scene);
    sun.position = position;
    const sunMaterial = this.material("sun-material", "#ffd366");
    sunMaterial.disableLighting = true;
    sunMaterial.emissiveColor = Color3.FromHexString("#ffd366");
    sun.material = sunMaterial;
    this.line("sun-direction", [Vector3.Zero(), position], "#ffd366");
    this.label("sun-label", `SOLEIL · ${data.solarConstellation}`,
      this.vector(data.longitude, data.latitude - 9, 1.08), "#ffd366", 0.58);
  }

  private fit() {
    const halfAngle = Math.atan(
      Math.tan(this.camera.fov / 2) * Math.min(1, this.engine.getAspectRatio(this.camera)),
    );
    this.camera.radius = Math.max(3.8, 1.65 / Math.sin(halfAngle));
    this.camera.upperRadiusLimit = Math.max(7, this.camera.radius);
  }

  reset() {
    this.camera.alpha = -this.data.azimuth * Math.PI / 180;
    this.camera.beta = Math.min(Math.PI - 0.05, Math.max(0.05,
      (90 - this.data.elevation) * Math.PI / 180));
    this.camera.setTarget(Vector3.Zero());
    this.interacted = false;
    this.fit();
  }

  focus(id: string) {
    const figure = this.data.constellations.find(item => item.id === id);
    if (!figure) { this.reset(); return; }
    this.interacted = true;
    this.camera.setPosition(this.vector(figure.longitude, figure.latitude, this.camera.radius));
  }

  setLayer(layer: Layer, enabled: boolean) {
    this.groups[layer].forEach(mesh => mesh.setEnabled(enabled));
  }

  private touch = () => { this.interacted = true; };
  private keyboard = (event: KeyboardEvent) => {
    this.interacted = true;
    if (event.key === "+" || event.key === "-") {
      this.camera.radius = Math.max(1.7, Math.min(this.camera.upperRadiusLimit ?? 10,
        this.camera.radius + (event.key === "+" ? -0.2 : 0.2)));
      event.preventDefault();
    }
  };
  private draw = () => this.scene.render();
  private renderState = () => {
    this.engine.stopRenderLoop(this.draw);
    if (!this.disposed && this.visible && !document.hidden) this.engine.runRenderLoop(this.draw);
  };

  dispose() {
    this.disposed = true;
    this.resize.disconnect();
    this.intersection.disconnect();
    document.removeEventListener("visibilitychange", this.renderState);
    this.canvas.removeEventListener("keydown", this.keyboard);
    this.canvas.removeEventListener("pointerdown", this.touch);
    this.canvas.removeEventListener("wheel", this.touch);
    this.engine.stopRenderLoop();
    this.scene.dispose();
    this.engine.dispose();
  }
}

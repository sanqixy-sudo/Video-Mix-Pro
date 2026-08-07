import { useState, useEffect } from "react";
import { Minus, Maximize2, Minimize2, X } from "lucide-react";
import brandHorizontal from "../assets/brand-horizontal-dark.png";

export function TitleBar({ blocked = false }: { blocked?: boolean }) {
  const [isMaximized, setIsMaximized] = useState(false);
  const [windowApi, setWindowApi] = useState<any>(null);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    try {
      import("@tauri-apps/api/window")
        .then((mod: any) => {
          const getWindow = mod.getCurrentWindow || mod.default?.getCurrentWindow;
          if (getWindow) {
            setWindowApi(() => getWindow);
          }
        })
        .catch(() => {
          // Not in Tauri runtime
        });
    } catch {
      // Not in Tauri runtime
    }
  }, []);

  useEffect(() => {
    if (!windowApi) return;
    const window = windowApi();
    let mounted = true;
    let unlisten: (() => void) | undefined;
    const handleResize = () => {
      window.isMaximized().then(setIsMaximized);
    };
    window.onResized(handleResize).then((cleanup: () => void) => {
      if (mounted) {
        unlisten = cleanup;
      } else {
        cleanup();
      }
    });
    handleResize();
    return () => {
      mounted = false;
      unlisten?.();
    };
  }, [windowApi]);

  const minimize = async () => {
    if (!windowApi) return;
    await windowApi().minimize();
  };

  const toggleMaximize = async () => {
    if (!windowApi) return;
    await windowApi().toggleMaximize();
    const maximized = await windowApi().isMaximized();
    setIsMaximized(maximized);
  };

  const closeWindow = async () => {
    if (!windowApi) return;
    await windowApi().close();
  };

  return (
    <header className="title-bar" data-tauri-drag-region inert={blocked ? true : undefined} aria-hidden={blocked || undefined}>
      <div className="title-bar-brand">
        <img src={brandHorizontal} alt="Video Mix Pro" />
      </div>
      <div className="title-bar-controls">
        <button className="title-bar-btn" onClick={minimize} aria-label="最小化">
          <Minus size={14} />
        </button>
        <button className="title-bar-btn" onClick={toggleMaximize} aria-label={isMaximized ? "还原" : "最大化"}>
          {isMaximized ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
        </button>
        <button className="title-bar-btn close" onClick={closeWindow} aria-label="关闭">
          <X size={14} />
        </button>
      </div>
    </header>
  );
}

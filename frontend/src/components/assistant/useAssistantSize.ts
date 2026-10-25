import { useRef, useState, type PointerEvent } from 'react';

interface Size { width: number; height: number }
function bounded(width: number, height: number): Size {
  const maxWidth = Math.max(0, window.innerWidth - 48);
  const maxHeight = Math.max(0, window.innerHeight - 48);
  return { width: Math.min(maxWidth, Math.max(340, width)), height: Math.min(maxHeight, Math.max(380, height)) };
}

export function useAssistantSize() {
  const [size, setSize] = useState<Size>();
  const drag = useRef<{ x: number; y: number; width: number; height: number } | null>(null);
  function start(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || window.innerWidth <= 640) return;
    const box = event.currentTarget.closest('.assistant-chat-window')!.getBoundingClientRect();
    drag.current = { x: event.clientX, y: event.clientY, width: box.width, height: box.height };
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    setSize(bounded(drag.current.width + drag.current.x - event.clientX, drag.current.height + drag.current.y - event.clientY));
  }
  return {
    style: size,
    customized: Boolean(size),
    toggle: () => setSize(current => current ? undefined : bounded(760, 800)),
    pointer: { onPointerDown: start, onPointerMove: move, onPointerUp: () => { drag.current = null; }, onPointerCancel: () => { drag.current = null; }, onLostPointerCapture: () => { drag.current = null; } },
  };
}

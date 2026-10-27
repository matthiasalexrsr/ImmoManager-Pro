import { useRef } from 'react';

export default function AnnotationSurface({ surface, annotations, kind, text, image, onAdd, onArea, disabled }) {
  const stroke = useRef(null);
  const pdfPoint = event => {
    const box = event.currentTarget.getBoundingClientRect();
    const [x, y] = surface.viewport.convertToPdfPoint(
      (event.clientX - box.left) * surface.width / box.width,
      (event.clientY - box.top) * surface.height / box.height);
    return [Math.max(0, Math.min(surface.view[2] - surface.view[0], x - surface.view[0])),
      Math.max(0, Math.min(surface.view[3] - surface.view[1], surface.view[3] - y))];
  };
  const point = value => surface.viewport.convertToViewportPoint(value[0] + surface.view[0], surface.view[3] - value[1]);
  return <svg className="document-annotation-surface" viewBox={`0 0 ${surface.width} ${surface.height}`}
    aria-label="Anmerkungsfläche: Bereich mit der Maus oder dem Stift aufziehen; alternativ Koordinaten eingeben"
    onPointerDown={event => {
      if (disabled) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      stroke.current = [pdfPoint(event)];
    }} onPointerMove={event => { if (stroke.current && stroke.current.length < 10000) stroke.current.push(pdfPoint(event)); }}
    onPointerUp={event => {
      if (!stroke.current) return;
      const points = [...stroke.current, pdfPoint(event)];
      stroke.current = null;
      const xs = points.map(value => value[0]); const ys = points.map(value => value[1]);
      const rect = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
      if (rect[2] - rect[0] < 2 || rect[3] - rect[1] < 2) return;
      const area = { page: surface.page, rect, rotation: surface.rotation };
      onArea(area);
      onAdd({ ...area, kind, text, points: ['freehand', 'drawn_signature'].includes(kind) ? points : [],
        image_base64: kind === 'image_signature' ? image : null });
    }} onPointerCancel={() => { stroke.current = null; }}>
    {annotations.filter(item => item.page === surface.page).map((item, index) => {
      const [x1, y1] = point(item.rect.slice(0, 2)); const [x2, y2] = point(item.rect.slice(2));
      const x = Math.min(x1, x2); const y = Math.min(y1, y2);
      if (['freehand', 'drawn_signature'].includes(item.kind)) return <polyline key={index}
        points={item.points.map(value => point(value).join(',')).join(' ')} fill="none" stroke="#143f7d" strokeWidth="2" />;
      return <g key={index}><rect x={x} y={y} width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)}
        fill={item.kind === 'highlight' ? '#ffdc3d' : 'white'} fillOpacity="0.4" stroke="#806300" />
        {item.kind === 'image_signature' && item.image_base64 ? <image href={`data:image/png;base64,${item.image_base64}`}
          x={x} y={y} width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)} />
          : <text x={x + 3} y={y + 14} fontSize="12" fill="#152e48">{item.text}</text>}</g>;
    })}
  </svg>;
}

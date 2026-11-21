import { useMemo } from 'react';
import { encode } from 'uqr';

/** A QR code drawn locally as SVG. Nothing is sent to a QR service. */
export function QrCode({ value, label }: { value: string; label: string }) {
  const { path, size } = useMemo(() => {
    const qr = encode(value, { ecc: 'M', border: 2 });
    const parts: string[] = [];
    qr.data.forEach((row, y) =>
      row.forEach((dark, x) => {
        if (dark) parts.push(`M${x} ${y}h1v1h-1z`);
      }),
    );
    return { path: parts.join(''), size: qr.size };
  }, [value]);

  return (
    <svg className="qr" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} shapeRendering="crispEdges">
      <rect width={size} height={size} fill="#fff" />
      <path d={path} fill="#17131c" />
    </svg>
  );
}

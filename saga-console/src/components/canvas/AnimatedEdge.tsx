/* ------------------------------------------------------------------ */
/* AnimatedEdge — custom edge with flowing particle during execution    */
/* ------------------------------------------------------------------ */
import { BaseEdge, type EdgeProps, getBezierPath } from '@xyflow/react';

export function AnimatedEdge(props: EdgeProps) {
  const {
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    style,
    data,
  } = props;

  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  const isAnimated = !!(data as Record<string, unknown>)?.animated;
  const status = (data as Record<string, unknown>)?.status as string | undefined;

  const edgeColor =
    status === 'success'
      ? '#10b981'
      : status === 'error'
        ? '#ef4444'
        : isAnimated
          ? '#3b82f6'
          : '#3f3f46';

  return (
    <>
      <BaseEdge
        id={props.id}
        path={edgePath}
        style={{
          stroke: edgeColor,
          strokeWidth: isAnimated || status ? 2.5 : 1.5,
          transition: 'stroke 0.4s, stroke-width 0.3s',
          ...style,
        }}
      />
      {isAnimated && (
        <circle r="3" fill="#60a5fa">
          <animateMotion
            dur="1.2s"
            repeatCount="indefinite"
            path={edgePath}
          />
        </circle>
      )}
    </>
  );
}

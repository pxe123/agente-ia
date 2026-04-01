import React, { useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";

export default function TiltCard({ children, className = "" }) {
  const reduce = useReducedMotion();
  const ref = useRef(null);
  const [style, setStyle] = useState({});

  const onMove = (e) => {
    if (reduce) return;
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    const rx = (py - 0.5) * -8;
    const ry = (px - 0.5) * 10;
    setStyle({
      transform: `perspective(900px) rotateX(${rx}deg) rotateY(${ry}deg) translateZ(0)`,
    });
  };

  const onLeave = () => setStyle({});

  const transition = useMemo(
    () => ({ type: "spring", stiffness: 260, damping: 22, mass: 0.6 }),
    []
  );

  return (
    <motion.div
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      style={style}
      transition={transition}
      className={className}
    >
      {children}
    </motion.div>
  );
}


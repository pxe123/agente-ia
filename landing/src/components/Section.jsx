import React from "react";
import { motion, useReducedMotion } from "framer-motion";

export default function Section({ id, className = "", children }) {
  const reduce = useReducedMotion();
  return (
    <section id={id} className={className}>
      <motion.div
        initial={reduce ? false : { opacity: 0, y: 18 }}
        whileInView={reduce ? {} : { opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.18 }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      >
        {children}
      </motion.div>
    </section>
  );
}


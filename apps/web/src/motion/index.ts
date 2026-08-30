// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

/**
 * The Ikarus motion system.
 *
 *   tokens.ts     the vocabulary — every duration, easing, spring, distance
 *   variants.ts   pure (tier, reduced) -> transition / variants resolvers
 *   useMotion.ts  the React edge: reduced-motion preference + token parity
 *   motion.css    hands transform/opacity ownership to JS on driven nodes
 *
 * Importing this module also loads motion.css, which is why every
 * motion-driven glass primitive imports from here rather than from the
 * sub-modules directly.
 */
import './motion.css';

export * from './tokens';
export * from './variants';
export * from './useMotion';
export * from './props';

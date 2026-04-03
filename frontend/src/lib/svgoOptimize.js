import { optimize } from 'svgo/browser'

/**
 * Optimize SVG text using SVGO to reduce node count and clean up output.
 * Only applied to the rounded result, not to overlays or diagnostics.
 * Falls back to the original string on any SVGO error.
 */
export function optimizeSvg(svgString) {
  if (!svgString) return svgString
  try {
    const result = optimize(svgString, {
      multipass: true,
      plugins: [
        'removeDoctype',
        'removeXMLProcInst',
        'removeComments',
        'removeMetadata',
        'removeEditorsNSData',
        'cleanupAttrs',
        { name: 'cleanupNumericValues', params: { floatPrecision: 4 } },
        'removeEmptyAttrs',
        'removeEmptyContainers',
        'removeUselessDefs',
        'collapseGroups',
        {
          name: 'convertPathData',
          params: {
            applyTransforms: false,
            straightCurves: true,
            convertToQ: false,
            lineShorthands: true,
            convertLines: false,
            curveSmoothShorthands: true,
            floatPrecision: 4,
            transformPrecision: 5,
            removeUseless: true,
            collapseRepeated: true,
            utilizeAbsolute: false,
            negativeExtraSpace: true,
          },
        },
        'removeUnusedNS',
      ],
    })
    return result.data
  } catch {
    return svgString
  }
}

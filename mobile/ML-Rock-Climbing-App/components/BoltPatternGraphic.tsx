import Svg, { Circle, Line } from 'react-native-svg'
import { BoltPattern } from '@/utils/boltPattern'

//Small drawing of each bolt-hole pattern for the Settings picker (slice 16):
//the holes, a faint outline of the shape they form, and the distance to
//measure in orange. "Squares with a centre hole" and "diamond" are the same
//holes - the outline and the measured gap are what differ.

const SIZE = 84
const MEASURE = '#ff8c00'
const OUTLINE = '#bbb'
const HOLE = '#333'

type Point = [number, number]

function layout(pattern: BoltPattern): { holes: Point[]; outline: [Point, Point][]; measure: [Point, Point] } {
  if (pattern === 'plain') {
    const g = [14, 33, 52, 71]
    const holes = g.flatMap((y) => g.map((x) => [x, y] as Point))
    const outline = g.flatMap((v) => [
      [[14, v], [71, v]] as [Point, Point],
      [[v, 14], [v, 71]] as [Point, Point],
    ])
    return { holes, outline, measure: [[14, 71], [33, 71]] }
  }
  //Corner holes every 30 px, a hole in the middle of each square.
  const corners = [12, 42, 72]
  const centres = [27, 57]
  const holes = [
    ...corners.flatMap((y) => corners.map((x) => [x, y] as Point)),
    ...centres.flatMap((y) => centres.map((x) => [x, y] as Point)),
  ]
  if (pattern === 'centred') {
    const outline = corners.flatMap((v) => [
      [[12, v], [72, v]] as [Point, Point],
      [[v, 12], [v, 72]] as [Point, Point],
    ])
    return { holes, outline, measure: [[12, 72], [42, 72]] }
  }
  //Diamond: the same holes, outlined as squares turned 45 degrees.
  const outline: [Point, Point][] = [
    [[12, 42], [42, 12]], [[12, 72], [72, 12]], [[42, 72], [72, 42]],
    [[12, 42], [42, 72]], [[12, 12], [72, 72]], [[42, 12], [72, 42]],
  ]
  return { holes, outline, measure: [[12, 72], [27, 57]] }
}

export function BoltPatternGraphic({ pattern }: { pattern: BoltPattern }) {
  const { holes, outline, measure } = layout(pattern)
  return (
    <Svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
      {outline.map(([a, b], i) => (
        <Line key={`o${i}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={OUTLINE} strokeWidth={1} />
      ))}
      <Line
        x1={measure[0][0]}
        y1={measure[0][1]}
        x2={measure[1][0]}
        y2={measure[1][1]}
        stroke={MEASURE}
        strokeWidth={4}
        strokeLinecap="round"
      />
      {holes.map(([x, y], i) => (
        <Circle key={`h${i}`} cx={x} cy={y} r={3.5} fill={HOLE} />
      ))}
    </Svg>
  )
}

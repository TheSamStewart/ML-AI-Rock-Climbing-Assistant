//The largest real "WxH" picture size the camera reports. Without an explicit
//pictureSize, takePictureAsync() sizes photos off the on-screen preview instead
//of the sensor's still-capture resolutions, and bolt detection needs the pixels.
//The list also holds qualitative aliases ("Photo", "High"), which are skipped.

export function largestPictureSize(sizes: string[] | undefined): string | undefined {
  if (!sizes) return undefined
  let best: { size: string; area: number } | null = null
  for (const size of sizes) {
    const match = /^(\d+)x(\d+)$/.exec(size)
    if (!match) continue
    const area = Number(match[1]) * Number(match[2])
    if (!best || area > best.area) best = { size, area }
  }
  return best?.size
}

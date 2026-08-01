# Anything about TS

## Typing in TS

- Typing in TS seems simple if you had take state `useState(null)`, this would start at null and during execution be set to a number. You would type as 
`useState<number | null>`. 
<br></br> 
This is not even close an important use-case, You can use this to type your objects together, you can also use the type on multiple of the same prop and anything.
<br></br>
```ts
type CustomCameraProps = {
    onCapture : (uri : string) => void
}

export function CustomCamera ({onCapture} : CustomCameraProps) {

}

```
Example only shows once but onCapture typing could be applied to any component that needs the same shape. e.g. a gallery picker that also hands back a photo uri:

```ts
export function GalleryPicker ({onCapture} : CustomCameraProps) {

}
```

Both `CustomCamera` and `GalleryPicker` now share one source of truth for what `onCapture` looks like.

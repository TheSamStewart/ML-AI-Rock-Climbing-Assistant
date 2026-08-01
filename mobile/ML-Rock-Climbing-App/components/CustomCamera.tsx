import { CameraView, CameraType } from 'expo-camera';
import { StyleSheet, View, Text, TouchableOpacity, Image, useWindowDimensions, Pressable} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import React, { useRef, useState } from 'react';

//Typing for props

type CustomCameraProps = {
  onCapture : (uri : string) => void
}

export function CustomCamera ({onCapture} : CustomCameraProps) {

    //Shutter size calculations

    const {width} = useWindowDimensions()
    const insets = useSafeAreaInsets()

    const size = width * 0.2;

    const shutter = {
        width: size,
        height: size,
        borderRadius: size / 2,
        borderWidth: size * 0.075,
    };

    //Camera ref - creates a reference to the native camera node in memory, allowing us to take pictures or videos
    
    const cameraRef = React.useRef<CameraView>(null)

    //isCapturing ref, 

    const isCapturing = useRef(false)

    //Camera states

    const [facing, setFacing] = useState<CameraType>('back')
    const [busy, setBusy] = useState(false)
    

    //Toggles the camera from front to back 

    function toggleFacing(){
        setFacing(current => (current === 'back' ? 'front' : 'back' ))
    }

    //Takes picture when shutter button is pressed

    const takePicture = async () => {

      //if camera is busy we return
        
      if(isCapturing.current) return

      //else we set the camera to busy and deal with the photo

        isCapturing.current = true
        setBusy(true)

        try{
          const photo = await cameraRef.current?.takePictureAsync();
          if(photo?.uri) onCapture(photo.uri);
        } 
        catch(e){
          console.error(e)
        }
        finally {
          isCapturing.current = false
          setBusy(false)
        }
    
      };

    //Render the camera

    return (
        <View style = {styles.container}>
            <CameraView ref = {cameraRef} style = {styles.camera} facing = {facing}/>
            <View style = {[styles.flipButtonContainer, { top: insets.top }]}>
                <TouchableOpacity onPress = {toggleFacing}>
                    <Image style = {styles.icon} source = {require('../assets/images/flipoutline_110902.png')}></Image>
                </TouchableOpacity>
            </View>
            <View style={[styles.shutterContainer, { bottom: insets.bottom + width * 0.06 }]}>
                <TouchableOpacity disabled = {busy} onPress={takePicture} style={[styles.shutter, shutter]}/>
            </View>
        </View> 
    )
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
  },
  camera: {
    flex: 1,
  },
  flipButtonContainer: {
    position: 'absolute',
    justifyContent: 'flex-end',
    flexDirection: 'row',
    backgroundColor: 'Transparent',
    width: '100%',
  },
  shutterContainer: {
    position: 'absolute',
    left: 0,
    right: 0,
    alignItems: 'center',
},
  shutter: {
    borderColor: 'white',
    backgroundColor: 'Transparent',
    shadowColor: 'black',
    shadowOpacity: 0.25,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 1 },
},
  text: {
    fontSize: 24,
    fontWeight: 'bold',
    color: 'white',
  },
  icon: {
    width: 48,
    height: 48,
    resizeMode: 'contain',
  },
});
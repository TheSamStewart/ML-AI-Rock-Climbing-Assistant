import {View , StyleSheet, Text, Button, Linking, Image} from 'react-native'
import { useCameraPermissions } from 'expo-camera'
import { CustomCamera } from '@/components/CustomCamera'
import { useState } from 'react';
import { SafeAreaView } from 'react-native-safe-area-context';

//default keyword here tells the expo router "This is the main content that needs to be rendered on this page" each page must have one default function
export default function Index(){

    //Photo uri state to render image, passed down to camera component

    const [uri, setUri] = useState<string | null>(null);

    //Camera Permission and Rendering 

    const [permission, requestPermission] = useCameraPermissions()

    //Camera permissions are loading

    if (!permission) {
        return(
            <View style = {styles.container}>
                <Text>Camera permissions are loading</Text>
            </View>
        )            
    }

    //Permissions are not granted yet

     if (!permission.granted) {
        
        //Check if we can prompt the user for permissions again, if turned off in settings simple button wont work

        const canPrompt = permission.canAskAgain

        //If we can prompt the user again, we prompt with button - Otherwise we send the user to settings

      return (
      <View style={styles.container}>
        <Text style={{textAlign: "center"}}>
          {canPrompt 
            ? "We need your permission to use the camera"
            : "Camera permission is turned off. Please enable in settings"}
        </Text>
        {canPrompt 
            ? (<Button onPress={requestPermission} title="Grant Permission" />) 
            : (
                <Button 
                    onPress={() => Linking.openSettings()} 
                    title="Open Device Settings" 
                /> 
            )}
      </View>
    );
  }

    //if no image taken yet, uri will be null and RN will render this

    if(!uri){
        return (
        <View style = {styles.container}>
            <CustomCamera onCapture = {setUri}/>
        </View>
    )}

    //If we have a photo render it, retake button sets the uri back to null

    return (
        <View style={styles.previewContainer}>
            <Image source={{ uri }} style={StyleSheet.absoluteFill} resizeMode="contain" />
            <SafeAreaView edges={['bottom']} style = {styles.previewActions}>
                <Button onPress={() => setUri(null)} title="Retake" />
                <Button title = 'Submit'/>
            </SafeAreaView>
            
        </View>
    ) 
    
}

//Styles

const styles = StyleSheet.create({
previewContainer: {
    flex : 1,
    justifyContent : 'flex-end'
},
preview : {
    flex : 1
},
previewActions: {
    flexDirection: 'row',
    justifyContent: 'space-evenly',
    alignItems: 'baseline',
    paddingVertical: 12,
},
message: {
    textAlign: 'center',
    paddingBottom: 10,
},
container: {
    flex: 1,
},
})
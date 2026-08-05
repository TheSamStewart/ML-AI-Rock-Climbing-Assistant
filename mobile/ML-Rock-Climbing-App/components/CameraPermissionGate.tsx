import { View, StyleSheet, Text, Button, Linking } from 'react-native'
import { useCameraPermissions } from 'expo-camera'
import { ReactNode } from 'react'

//Handles camera permission state only - renders children once permission is granted.
//Keeps permission loading/prompt/settings UI out of screens that just need a camera.

type CameraPermissionGateProps = {
  children: ReactNode
}

export function CameraPermissionGate({ children }: CameraPermissionGateProps) {
  const [permission, requestPermission] = useCameraPermissions()

  //Camera permissions are loading

  if (!permission) {
    return (
      <View style={styles.container}>
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
        <Text style={{ textAlign: 'center' }}>
          {canPrompt
            ? 'We need your permission to use the camera'
            : 'Camera permission is turned off. Please enable in settings'}
        </Text>
        {canPrompt ? (
          <Button onPress={requestPermission} title="Grant Permission" />
        ) : (
          <Button onPress={() => Linking.openSettings()} title="Open Device Settings" />
        )}
      </View>
    )
  }

  //Permission granted - render whatever needs the camera

  return <>{children}</>
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
    gap: 12,
  },
})

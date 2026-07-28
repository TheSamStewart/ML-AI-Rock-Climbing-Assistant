import { StyleSheet, View, Text} from 'react-native';

export default function Index(){
    return (
        <View style = {styles.container}>
            <Text style = {styles.title}>Danielle is a cheeky chicken</Text>
        </View>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#fff',
        alignItems: 'center',
        justifyContent: 'center' 
    },
    title: {
        fontWeight: 'bold',
        fontSize: 18
    }
})
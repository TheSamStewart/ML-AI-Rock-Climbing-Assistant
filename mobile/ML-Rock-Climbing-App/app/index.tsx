import { StyleSheet, View, Text} from 'react-native';


//default keyword here tells the expo router "This is the main content that needs to be rendered on this page" each page must have one default function
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
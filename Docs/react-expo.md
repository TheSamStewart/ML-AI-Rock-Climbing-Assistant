# NOTES ON REACT/EXPO for learning

## What each folder/file in the project template is/does

### .expo

- This is local cache and temp state folder created by the Expo CLI and can be safely deleted. Deletion can fix issues with expo/metro and it will be created again when we run npx expo start.

### .vscode

- This stores information about extensions and settings enforced by VS Code like save on exit or Linting. This is workspace specific.

### node_modules

- This stores all the JavaScript code for the dependencies and should be in .gitignore. It is called a node because in JavaScript any self-contained that exports logic for another file to import is called a module.

### app/package/package-lock.json

#### app.json

- This is the configuration file for the app, it sets things like the app name, favicon/app icon. It also configures plugins like the expo-router, which tells Metro to watch the app directory

#### package.json

- This is a definition of all external dependencies and libraries the project requires to function like expo-router, React etc.

#### package-lock.json

- This is a definition of the exact versions and depedency trees of these dependencies. For example in package.json we have "React" : ^12.0, package.lock holds: the exact installed version (^ allows any minor updates or patches like 12.0.4), The security hash to ensure the file hasn't been tampered with and the dependency tree that this version of React relies on.

### expo-env.d.ts

- This file supplies the TS compiler with information it needs to allow us to use it in a way that is different from normal. For example it tells the TS to allow React features like importing images and also tells the compiler to allow references to environment variables as they will be supplied at run time.

### tsconfig.json

- This is a config file for TS which tells the TS compiler what files to compile before execution time and how to compile.

### app

- Files for the application need to live here as this is what expo-router expects, expo router allows us to manage screen navigation otherwise would need manual navigation config files.

## What is Metro

- Metro is responosible for watching the /app directory and telling Expo to update the **routing graph**. If any changes occur, Expo uses this information to map actual filenames to their reference in the routing graph. If we want to send the user to a different part of the application using router.push('/path'), expo uses the routing graph to tell Metro to render this page.

## export defauly function

- The default keyword here tells the expo router that this is the main content that needs to be displayed on this page, each page needs a default function or error.

## React-Native-Expo-Camera

- The photo.uri points to the location of the image inside local cache storage.

## Bundle Identifier

- This is used by app store/android store to uniquely identify the app.

## ref vs state

- ref is a reference to a piece of memory outside, that can be accessed at any point in any render meaning any changes due to this will be applied until the component is unmounted
- state is per render setX doesnt change the current value, it schedules a new render where x is created.
- if changing it should change what's on screen, it's state; if it shouldn't, it's a ref

# Notes on Tanstack

## Overview

- Makes fetching/recieving data with APIs more efficient in terms of runtime with caching and managing memory.
- Improves dev experience by providing state like isPending, Success, error and data automatically. Provides Query Options like refetch interval.

## Implementation notes

1. Initialise the queryClient and wrap the app in the QueryClientProvider tags.

```tsx
const queryClient = new QueryClient();

export default function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <Stack screenOptions={{ headerShown: false }} />
    </QueryClientProvider>
  );
}
```

2. Create a function which sends the request to the API endpoint.

```tsx
export async function climbAnalysis(uri: string) {
  const filename = uri.split("/").pop() ?? `climb-${Date.now()}.jpg`;
  const ext = /\.(\w+)$/.exec(filename)?.[1] ?? "jpg";

  //Create the formData for the request

  const formData = new FormData();
  formData.append("photo", {
    uri,
    name: filename,
    type: `image/${ext === "jpg" ? "jpeg" : ext}`,
  } as any);

  //make the request

  const res = await fetch("http://localhost:8000/analysis", {
    method: "POST",
    body: formData,
  });

  if (!res.ok) throw new Error(`Analyze failed: ${res.status}`);
  return res.json();
}
```

3. Create a hook that uses the correct tanstack hook to deal with things like caching and refetching in the background. Here useMutation is used as useMutation doesnt perform any caching or refetching, matching the use case for POST.

```tsx
import { useMutation } from "@tanstack/react-query";
import { climbAnalysis } from "@/api/climbAnalysis";

//useMutation does not retry in the background or need to be cached, better for POST instead of useQuery
//useQuery will be used for the GET polling request

export function useClimbAnalysis() {
  return useMutation({ mutationFn: climbAnalysis });
}
```

4. Create the state for the useClimbAnalysis hook and pass to the button or code that triggers the request.

   ```tsx
   const { mutate, isPending, isError, error } = useClimbAnalysis();
   ```

5. When mutate() is called this uses the useClimbAnalysis hook which makes the API request and returns information about the state of the request. When we have recieved the response from the server, this will end up in data and we can access using data.{data_needed}
   ```tsx
   <Button
     onPress={() =>
       mutate(uri, { onSuccess: (data) => onSubmitted(data.task_id) })
     }
     title={isPending ? "Submitting…" : "Submit"}
     disabled={isPending}
   />
   ```

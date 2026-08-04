# Notes on Tanstack

## Overview

- Makes fetching/recieving data with APIs more efficient in terms of runtime and developer experience
- Provides hooks for data, isLoading, isError
- Caches queries

## Video notes

- Initialise the queryClient, and wrap the app < QueryClientProvider client = {queryClient}>
- queryKey = unique key for queryKey
- queryFn = function that runs when we make a call 
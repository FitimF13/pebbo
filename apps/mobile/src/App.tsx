import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Alert, Linking, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { DarkTheme, DefaultTheme, NavigationContainer, type Theme as NavigationTheme } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { parsePairingLink, type PairingTarget } from '@pebbo/contracts';
import { ApiError, createClient } from './api/client';
import { Icon, type IconName } from './components/Icons';
import { usePendingNotifications } from './notifications';
import { loadCredentials, unpairPhone, type Credentials } from './pairing';
import { ChatScreen } from './screens/ChatScreen';
import { MemoriesScreen } from './screens/MemoriesScreen';
import { PairingScreen } from './screens/PairingScreen';
import { RemindersScreen } from './screens/RemindersScreen';
import { SettingsScreen } from './screens/SettingsScreen';
import { SessionContext, type Session } from './session';
import { secureCredentials } from './storage';
import { useTheme, type Theme } from './theme';

const REMOVED = 'Dieses Handy wurde im Kontrollzentrum entkoppelt. Koppel es neu, um weiter mit Pebbo zu chatten.';

export function App() {
  const theme = useTheme();
  // undefined while loading, null when this phone is not paired.
  const [credentials, setCredentials] = useState<Credentials | null>();
  const [target, setTarget] = useState<PairingTarget>();
  const [notice, setNotice] = useState<string>();

  useEffect(() => {
    void loadCredentials(secureCredentials).then((stored) => setCredentials(stored ?? null));
  }, []);

  // The QR code in the control centre is a pebbo://pair link that the camera opens here.
  useEffect(() => {
    const open = (url: string | null | undefined) => {
      const link = url ? parsePairingLink(url) : undefined;
      if (link) setTarget(link);
    };
    void Linking.getInitialURL().then(open);
    const subscription = Linking.addEventListener('url', ({ url }) => open(url));
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    if (credentials && target) {
      Alert.alert('Schon gekoppelt', 'Entkopple dieses Handy zuerst in den Einstellungen, um es neu zu koppeln.');
      setTarget(undefined);
    }
  }, [credentials, target]);

  const forget = useCallback(async (reason?: string) => {
    await secureCredentials.clear();
    setNotice(reason);
    setCredentials(null);
  }, []);

  return (
    <SafeAreaProvider>
      <StatusBar style={theme.dark ? 'light' : 'dark'} />
      {credentials === undefined ? (
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.background }}>
          <ActivityIndicator color={theme.accent} />
        </View>
      ) : credentials === null ? (
        <PairingScreen
          target={target}
          notice={notice}
          onPaired={(paired) => {
            setTarget(undefined);
            setNotice(undefined);
            setCredentials(paired);
          }}
        />
      ) : (
        <Paired credentials={credentials} forget={forget} />
      )}
    </SafeAreaProvider>
  );
}

function Paired({ credentials, forget }: { credentials: Credentials; forget(reason?: string): Promise<void> }) {
  const theme = useTheme();
  const client = useMemo(
    () => createClient({ address: credentials.address, token: credentials.token, fetch: (input, init) => fetch(input, init) }),
    [credentials],
  );

  const explain = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.unpaired) {
        void forget(REMOVED);
        return REMOVED;
      }
      return error instanceof Error ? error.message : 'Das hat nicht geklappt.';
    },
    [forget],
  );

  const session = useMemo<Session>(
    () => ({
      credentials,
      client,
      explain,
      unpair: async () => {
        await unpairPhone(client.unpair, secureCredentials);
        await forget();
      },
    }),
    [credentials, client, explain, forget],
  );

  const { pending, acknowledge } = usePendingNotifications(client, explain);

  return (
    <SessionContext.Provider value={session}>
      <NavigationContainer theme={navigationTheme(theme)}>
        <Tab.Navigator
          screenOptions={({ route }) => ({
            tabBarIcon: ({ color, size }) => <Icon name={ICONS[route.name]} color={color} size={size} />,
            tabBarActiveTintColor: theme.accent,
            tabBarInactiveTintColor: theme.muted,
            headerShadowVisible: false,
            headerTitleStyle: { fontWeight: '700' },
          })}
        >
          <Tab.Screen name="Chat" options={{ headerShown: false }}>
            {() => <ChatScreen pending={pending} onAcknowledge={() => void acknowledge()} />}
          </Tab.Screen>
          <Tab.Screen
            name="Erinnerungen"
            component={RemindersScreen}
            options={pending.length > 0 ? { tabBarBadge: pending.length } : {}}
          />
          <Tab.Screen name="Gedächtnis" component={MemoriesScreen} />
          <Tab.Screen name="Einstellungen" component={SettingsScreen} />
        </Tab.Navigator>
      </NavigationContainer>
    </SessionContext.Provider>
  );
}

type Tabs = { Chat: undefined; Erinnerungen: undefined; Gedächtnis: undefined; Einstellungen: undefined };

const Tab = createBottomTabNavigator<Tabs>();

const ICONS: Record<keyof Tabs, IconName> = {
  Chat: 'chat',
  Erinnerungen: 'bell',
  Gedächtnis: 'memory',
  Einstellungen: 'settings',
};

function navigationTheme(theme: Theme): NavigationTheme {
  const base = theme.dark ? DarkTheme : DefaultTheme;
  return {
    ...base,
    colors: {
      ...base.colors,
      primary: theme.accent,
      background: theme.background,
      card: theme.card,
      text: theme.text,
      border: theme.cardBorder,
      notification: theme.glowStrong,
    },
  };
}

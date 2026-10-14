<?php

namespace App\Console\Commands;

use App\Models\User;
use Illuminate\Console\Command;
use Illuminate\Support\Str;

class CreateToken extends Command
{
    protected $signature = 'misnotas:token {email : Correo del usuario (se crea si no existe)} {--name=mac : Nombre del dispositivo}';

    protected $description = 'Crea un token de acceso para la app Mis Notas';

    public function handle(): int
    {
        $user = User::firstOrCreate(
            ['email' => $this->argument('email')],
            ['name' => Str::before($this->argument('email'), '@'), 'password' => Str::random(40)],
        );

        $token = $user->createToken($this->option('name'))->plainTextToken;

        $this->info('Token creado. Cópialo en Ajustes de Mis Notas (no se volverá a mostrar):');
        $this->line($token);

        return self::SUCCESS;
    }
}
